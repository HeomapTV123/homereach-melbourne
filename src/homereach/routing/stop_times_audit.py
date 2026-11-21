"""Stream a fixed-stop timetable into a temporary, ordered audit index.

The index is disposable and never becomes a routing input. It lets the audit
check complete trips without assuming CSV order or retaining millions of rows
in Python memory. Unsupported service semantics remain explicit blockers.
"""
from __future__ import annotations

from collections import Counter
from contextlib import closing
from dataclasses import dataclass, field
import csv
from pathlib import Path
import re
import sqlite3
from tempfile import TemporaryDirectory
from typing import Callable, TextIO


BATCH_SIZE = 10_000
EXAMPLE_LIMIT = 5
PROGRESS_ROWS = 250_000
MAX_EXAMPLE_TEXT = 160
SQLITE_MAX_INTEGER = 2**63 - 1
_DIGITS = re.compile(r"[0-9]+")
_TIME = re.compile(r"([0-9]+):([0-5][0-9]):([0-5][0-9])")
_FORBIDDEN_FIELD_CHARACTERS = re.compile(r"[\t\r\n]")
_FLEX_FIELDS = (
    "location_id", "location_group_id", "start_pickup_drop_off_window",
    "end_pickup_drop_off_window", "pickup_booking_rule_id", "drop_off_booking_rule_id",
)
_REQUIRED_FIELDS = {"trip_id", "stop_sequence"}
_TIME_FIELDS = {"arrival_time", "departure_time"}
_UNORDERABLE = 1
_UNTIMED = 2
_UNSUPPORTED = 4
_INSERT = "INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?)"


class _Findings:
    def __init__(self) -> None:
        self.values: dict[str, dict] = {}

    def add(self, code: str, severity: str, *, count: int = 1, **example) -> None:
        finding = self.values.setdefault(code, {
            "code": code, "severity": severity, "count": 0, "examples": [],
        })
        if finding["severity"] != severity:
            raise ValueError(f"Conflicting severity for {code}.")
        finding["count"] += count
        if example and len(finding["examples"]) < EXAMPLE_LIMIT:
            finding["examples"].append({
                key: value[:MAX_EXAMPLE_TEXT] if isinstance(value, str) else value
                for key, value in example.items()
            })

    def report(self) -> list[dict]:
        order = {"error": 0, "blocked": 1, "info": 2}
        return sorted(self.values.values(), key=lambda item: (order[item["severity"]], item["code"]))


@dataclass
class _Context:
    trips: list[str]
    active: set[str]
    stops: dict[str, str]
    continuous: dict[str, tuple[str, str]]
    progress: Callable[[str], None] | None
    findings: _Findings = field(default_factory=_Findings)
    counts: Counter = field(default_factory=Counter)
    minimum: int | None = None
    maximum: int | None = None
    all_orderable: bool = True

    def __post_init__(self) -> None:
        self.trip_index = {name: index for index, name in enumerate(self.trips)}
        self.trip_rows = [0] * len(self.trips)
        self.trip_flags = bytearray(len(self.trips))

    def notify(self, message: str) -> None:
        if self.progress is not None:
            self.progress(message)


def _bounded_integer(value: str) -> int | None:
    significant = value.lstrip("0") or "0"
    limit = str(SQLITE_MAX_INTEGER)
    if len(significant) > len(limit) or (len(significant) == len(limit) and significant > limit):
        return None
    return int(significant)


def _time_seconds(value: str) -> tuple[int | None, str | None]:
    if not value:
        return None, None
    match = _TIME.fullmatch(value)
    if match is None:
        return None, "invalid"
    hour = _bounded_integer(match[1])
    if hour is None or hour > SQLITE_MAX_INTEGER // 3600:
        return None, "range"
    result = hour * 3600 + int(match[2]) * 60 + int(match[3])
    return (result, None) if result <= SQLITE_MAX_INTEGER else (None, "range")


def _read_header(reader: csv.reader) -> tuple[list[str], dict[str, int]]:
    header = next(reader, None)
    if not header:
        raise ValueError("stop_times.txt has no header.")
    # A caller normally decodes utf-8-sig. Also accept a decoded BOM in TextIO.
    if header[0].startswith("\ufeff"):
        header[0] = header[0][1:]
    if any(not name or name != name.strip() for name in header):
        raise ValueError("stop_times.txt has a blank or padded header column.")
    if any(_FORBIDDEN_FIELD_CHARACTERS.search(name) for name in header):
        raise ValueError("stop_times.txt has a forbidden control character in a header column.")
    if len(header) != len(set(header)):
        raise ValueError("stop_times.txt has duplicate header columns.")
    missing = _REQUIRED_FIELDS - set(header)
    flex_schema = set(header).intersection(_FLEX_FIELDS)
    if not flex_schema:
        missing |= _TIME_FIELDS - set(header)
    if not {"location_id", "location_group_id"}.intersection(header) and "stop_id" not in header:
        missing.add("stop_id")
    if missing:
        raise ValueError("stop_times.txt is missing required columns: " + ", ".join(sorted(missing)))
    return header, {name: number for number, name in enumerate(header)}


def _flush_rows(connection: sqlite3.Connection, batch: list[tuple], context: _Context) -> None:
    if not batch:
        return
    before = connection.total_changes
    connection.executemany(_INSERT, batch)
    duplicates = len(batch) - (connection.total_changes - before)
    if duplicates:
        context.findings.add("duplicate_trip_sequence", "error", count=duplicates)
        context.all_orderable = False
        # Only a batch containing duplicates needs these lookups. All duplicated
        # trip IDs are flagged even after the bounded example list is full.
        for row in batch:
            first = connection.execute(
                "SELECT data_row FROM events WHERE trip_index = ? AND sequence = ?",
                row[:2],
            ).fetchone()[0]
            if first != row[2]:
                context.trip_flags[row[0]] |= _UNORDERABLE
                context.findings.add(
                    "duplicate_trip_sequence", "error", count=0,
                    trip_id=context.trips[row[0]], stop_sequence=row[1],
                    data_row=row[2], line_end=row[3], first_data_row=first,
                )
    context.counts["distinct_trip_sequence_rows_indexed"] += len(batch) - duplicates
    batch.clear()


def _enum_fields(values: dict[str, str], context: _Context, example: dict) -> bool:
    arrangement = False
    for name in ("pickup_type", "drop_off_type"):
        value = values[name]
        if value not in ("", "0", "1", "2", "3"):
            context.findings.add("invalid_" + name, "error", **example, value=value)
        arrangement |= value in ("2", "3")
    if arrangement:
        context.counts["arrangement_required_rows"] += 1
        context.findings.add("arrangement_required", "info", **example)
    if values["timepoint"] not in ("", "0", "1"):
        context.findings.add("invalid_timepoint", "error", **example, value=values["timepoint"])
    unsupported = False
    defaults = context.continuous.get(values["trip_id"], ("", ""))
    for number, name in enumerate(("continuous_pickup", "continuous_drop_off")):
        effective = values[name] or defaults[number] or "1"
        if effective not in ("0", "1", "2", "3"):
            context.findings.add("invalid_" + name, "error", **example, value=effective)
        unsupported |= effective in ("0", "2", "3")
    if unsupported:
        context.counts["effective_continuous_service_rows"] += 1
        context.findings.add("unsupported_continuous_service", "blocked", **example)
    return unsupported


def _check_times(values: dict[str, str], flexible: bool, context: _Context, example: dict):
    parsed = []
    parse_problem = False
    for name in ("arrival_time", "departure_time"):
        seconds, problem = _time_seconds(values[name])
        parsed.append(seconds)
        if problem:
            parse_problem = True
            if problem == "invalid":
                context.findings.add("invalid_" + name, "error", **example, value=values[name])
            else:
                context.findings.add("time_out_of_range", "blocked", **example, field=name, value=values[name])
    arrival, departure = parsed
    known = [value for value in parsed if value is not None]
    if known:
        minimum, maximum = min(known), max(known)
        context.minimum = minimum if context.minimum is None else min(context.minimum, minimum)
        context.maximum = maximum if context.maximum is None else max(context.maximum, maximum)
        if maximum >= 86400:
            context.counts["rows_with_extended_times"] += 1
            if values["trip_id"] in context.active:
                context.counts["active_rows_with_extended_times"] += 1
    missing = (not values["arrival_time"]) | ((not values["departure_time"]) << 1)
    if not flexible:
        if missing in (1, 2):
            context.findings.add("unpaired_times", "error", **example)
        elif missing == 3:
            context.counts["rows_with_unresolved_times"] += 1
            context.findings.add("unresolved_times", "blocked", **example)
        if missing and values["timepoint"] == "1":
            context.findings.add("missing_timepoint_times", "error", **example)
        if arrival is not None and departure is not None and departure < arrival:
            context.findings.add("departure_before_arrival", "error", **example,
                                 arrival_seconds=arrival, departure_seconds=departure)
    return arrival, departure, missing, parse_problem


def _scan_rows(reader, header: list[str], positions: dict[str, int],
               connection: sqlite3.Connection, context: _Context) -> None:
    names = ("trip_id", "stop_sequence", "stop_id", "arrival_time", "departure_time",
             "timepoint", "pickup_type", "drop_off_type", "continuous_pickup",
             "continuous_drop_off", *_FLEX_FIELDS)
    getters = [(name, positions.get(name)) for name in names]
    missing_time_columns = not _TIME_FIELDS.issubset(positions)
    batch: list[tuple] = []
    for row in reader:
        if not row:
            context.counts["blank_records_ignored"] += 1
            continue
        context.counts["rows_scanned"] += 1
        number = context.counts["rows_scanned"]
        if number % PROGRESS_ROWS == 0:
            context.notify(f"Scanned {number:,} stop-time rows.")
        if any(_FORBIDDEN_FIELD_CHARACTERS.search(value) for value in row):
            context.findings.add("forbidden_field_characters", "error", data_row=number,
                                 line_end=reader.line_num)
            context.all_orderable = False
        if len(row) != len(header):
            context.findings.add("invalid_field_count", "error", data_row=number,
                                 line_end=reader.line_num, expected_fields=len(header), actual_fields=len(row))
            context.all_orderable = False
            candidate = row[positions["trip_id"]] if len(row) > positions["trip_id"] else ""
            if candidate in context.trip_index:
                context.trip_flags[context.trip_index[candidate]] |= _UNORDERABLE
            continue
        values = {name: row[index] if index is not None else "" for name, index in getters}
        trip_id = values["trip_id"]
        example = {"data_row": number, "line_end": reader.line_num, "trip_id": trip_id}
        trip_index = context.trip_index.get(trip_id)
        if not trip_id or trip_id != trip_id.strip():
            context.findings.add("invalid_trip_id", "error", **example)
            context.all_orderable = False
        elif trip_index is None:
            context.findings.add("unknown_trip", "error", **example)
            context.all_orderable = False
        else:
            context.trip_rows[trip_index] += 1
            if trip_id in context.active:
                context.counts["active_rows_scanned"] += 1

        sequence_text = values["stop_sequence"]
        sequence = None
        if not _DIGITS.fullmatch(sequence_text):
            context.findings.add("invalid_stop_sequence", "error", **example, value=sequence_text)
        else:
            sequence = _bounded_integer(sequence_text)
            if sequence is None:
                context.findings.add("stop_sequence_out_of_range", "blocked", **example, value=sequence_text)
        if sequence is None:
            context.all_orderable = False
            if trip_index is not None:
                context.trip_flags[trip_index] |= _UNORDERABLE

        populated_flex = [name for name in _FLEX_FIELDS if values[name]]
        flexible = bool(populated_flex)
        if flexible:
            context.counts["flexible_service_rows"] += 1
            context.findings.add("unsupported_flexible_service", "blocked", **example,
                                 fields=", ".join(populated_flex))
        else:
            stop_id = values["stop_id"]
            if not stop_id or stop_id != stop_id.strip():
                context.findings.add("invalid_stop_id", "error", **example, stop_id=stop_id)
            elif stop_id not in context.stops:
                context.findings.add("unknown_stop", "error", **example, stop_id=stop_id)
            elif context.stops[stop_id] not in ("", "0"):
                context.findings.add("non_boarding_stop", "error", **example,
                                     stop_id=stop_id, location_type=context.stops[stop_id])
            if missing_time_columns:
                context.findings.add("missing_fixed_stop_time_columns", "error", **example)

        continuous = _enum_fields(values, context, example)
        arrival, departure, missing, parse_problem = _check_times(values, flexible, context, example)
        unsupported = flexible or continuous or parse_problem
        if trip_index is not None:
            if missing:
                context.trip_flags[trip_index] |= _UNTIMED
            if unsupported:
                context.trip_flags[trip_index] |= _UNSUPPORTED
        if trip_index is not None and sequence is not None:
            batch.append((trip_index, sequence, number, reader.line_num,
                          arrival, departure, missing, int(unsupported)))
            if len(batch) >= BATCH_SIZE:
                _flush_rows(connection, batch, context)
    _flush_rows(connection, batch, context)
    connection.commit()


def _check_trip_edges(first: tuple, last: tuple, context: _Context) -> None:
    trip_index = first[0]
    if context.trip_flags[trip_index] & (_UNORDERABLE | _UNSUPPORTED):
        return
    edges = [(first, "first_and_last")] if first[2] == last[2] else [(first, "first"), (last, "last")]
    for row, position in edges:
        if row[6]:
            context.findings.add("missing_trip_edge_times", "error", trip_id=context.trips[trip_index],
                                 data_row=row[2], line_end=row[3], stop_sequence=row[1], position=position)


def _inspect_ordered(connection: sqlite3.Connection, context: _Context) -> None:
    context.notify("Checking complete trips in numeric stop-sequence order.")
    first = last = None
    previous_departure = None
    previous_departure_row = None
    checked = 0
    for row in connection.execute("SELECT * FROM events ORDER BY trip_index, sequence"):
        checked += 1
        if checked % PROGRESS_ROWS == 0:
            context.notify(f"Checked {checked:,} indexed rows in trip order.")
        if last is None or row[0] != last[0]:
            if last is not None:
                _check_trip_edges(first, last, context)
            first = row
            previous_departure = previous_departure_row = None
        if row[7]:
            # A Flex/unsupported row's semantics are not a known fixed-stop
            # timing anchor. Do not bridge it and claim full chronology.
            previous_departure = previous_departure_row = None
        else:
            arrival, departure = row[4:6]
            if arrival is not None and previous_departure is not None and arrival < previous_departure:
                context.findings.add("chronology_reversal", "error", trip_id=context.trips[row[0]],
                                     data_row=row[2], line_end=row[3], stop_sequence=row[1],
                                     arrival_seconds=arrival, previous_departure_seconds=previous_departure,
                                     previous_data_row=previous_departure_row)
            if departure is not None:
                previous_departure = departure
                previous_departure_row = row[2]
        last = row
    if last is not None:
        _check_trip_edges(first, last, context)
    context.counts["ordered_rows_checked"] = checked


def audit_stop_times(
    text: TextIO,
    *,
    trip_ids: set[str],
    active_trip_ids: set[str],
    stop_types: dict[str, str],
    workspace: Path,
    expected_rows: int | None = None,
    progress: Callable[[str], None] | None = None,
    continuous_defaults: dict[str, tuple[str, str]] | None = None,
) -> dict:
    """Audit all supplied rows, retaining bounded examples and a disposable index.

    ``workspace`` must be an existing private temporary directory supplied by
    the caller. Recoverable row violations produce an ``invalid`` report;
    unreadable CSV or an unusable header raises ValueError. ``blocked`` means
    this fixed-stop/timed scope cannot establish completeness, not invalid GTFS.
    ``passed`` applies only to these checks and never establishes routing.
    """
    if not active_trip_ids.issubset(trip_ids):
        raise ValueError("Active trip identifiers must be a subset of declared trips.")
    if any(not isinstance(value, str) or not value or value != value.strip() for value in trip_ids):
        raise ValueError("Declared trip identifiers must be complete, unpadded strings.")
    if expected_rows is not None and (type(expected_rows) is not int or expected_rows < 0):
        raise ValueError("expected_rows must be a nonnegative integer or None.")
    if not Path(workspace).is_dir():
        raise ValueError("The temporary audit workspace must already exist.")
    defaults = continuous_defaults or {}
    if any(key not in trip_ids or not isinstance(value, (tuple, list)) or len(value) != 2
           or any(item not in ("", "0", "1", "2", "3") for item in value)
           for key, value in defaults.items()):
        raise ValueError("Continuous defaults must contain valid pickup/drop-off pairs for declared trips.")
    context = _Context(sorted(trip_ids), active_trip_ids, stop_types, defaults, progress)
    reader = csv.reader(text, strict=True)
    try:
        header, positions = _read_header(reader)
        with TemporaryDirectory(prefix="stop-time-index-", dir=workspace) as directory:
            with closing(sqlite3.connect(Path(directory) / "events.sqlite")) as connection:
                # All changes affect a fresh disposable DB. The primary key is
                # also the ordered index, so no all-row external sort is needed.
                connection.execute("PRAGMA journal_mode=OFF")
                connection.execute("PRAGMA synchronous=OFF")
                connection.execute("PRAGMA temp_store=MEMORY")
                connection.execute("PRAGMA cache_size=-32768")
                connection.execute("""CREATE TABLE events (
                    trip_index INTEGER NOT NULL, sequence INTEGER NOT NULL,
                    data_row INTEGER NOT NULL, line_end INTEGER NOT NULL,
                    arrival INTEGER, departure INTEGER, missing INTEGER NOT NULL,
                    unsupported INTEGER NOT NULL,
                    PRIMARY KEY (trip_index, sequence)
                ) WITHOUT ROWID""")
                _scan_rows(reader, header, positions, connection, context)
                _inspect_ordered(connection, context)
    except csv.Error as error:
        raise ValueError(f"Cannot parse stop_times.txt near physical line {reader.line_num}: {error}") from error

    if expected_rows is not None and context.counts["rows_scanned"] != expected_rows:
        context.findings.add("row_count_mismatch", "error", expected_rows=expected_rows,
                             actual_rows=context.counts["rows_scanned"])
    for index, trip in enumerate(context.trips):
        count = context.trip_rows[index]
        active = trip in active_trip_ids
        if count == 0:
            context.findings.add("active_trip_without_stop_times" if active else "unused_trip",
                                 "blocked" if active else "info", trip_id=trip)
        elif count < 2:
            context.findings.add("active_trip_too_short" if active else "inactive_trip_too_short",
                                 "blocked" if active else "info", trip_id=trip, stop_time_rows=count)
    issues = context.findings.report()
    severities = {item["severity"] for item in issues}
    status = "invalid" if "error" in severities else "blocked" if "blocked" in severities else "passed"
    metric_names = (
        "rows_scanned", "active_rows_scanned", "blank_records_ignored",
        "distinct_trip_sequence_rows_indexed", "ordered_rows_checked",
        "rows_with_extended_times", "active_rows_with_extended_times",
        "rows_with_unresolved_times", "arrangement_required_rows",
        "flexible_service_rows", "effective_continuous_service_rows",
    )
    return {
        "status": status, "scan_complete": True,
        "logical_trip_checks_complete": context.all_orderable and not any(context.trip_flags),
        "stop_times_header": header,
        **{name: context.counts[name] for name in metric_names},
        "declared_trip_records": len(trip_ids), "active_trip_records": len(active_trip_ids),
        "known_trips_with_rows": sum(count > 0 for count in context.trip_rows),
        "active_trips_with_rows": sum(context.trip_rows[index] > 0 for index, trip in enumerate(context.trips)
                                      if trip in active_trip_ids),
        "minimum_time_seconds": context.minimum, "maximum_time_seconds": context.maximum,
        "issues": issues,
    }
