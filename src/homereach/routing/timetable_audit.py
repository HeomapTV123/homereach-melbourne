"""Read-only, pinned GTFS timetable audit; never initialize a routing engine.

Nested ZIP bytes and the stop-time index use a caller-selected temporary
directory outside the checkout. Source paths remain governed by the existing
pilot/snapshot contract. This is a scoped audit, not complete GTFS certification.
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
import csv
from datetime import date
import io
from pathlib import Path
import shutil
import sqlite3
from tempfile import SpooledTemporaryFile, TemporaryDirectory, gettempdir
from zipfile import BadZipFile, ZipFile

import pandas as pd

from homereach.transport.gtfs import (
    REQUIRED_COLUMNS, TABLE_NAMES, build_active_trips, require, require_key,
    sha256_file,
)
from homereach.transport.snapshot import load_transport_snapshot
from .preflight import PILOT_CONFIG_PATH, _load_inputs, _project_path
from .stop_times_audit import audit_stop_times


NOT_VALIDATED = [
    "Routing-engine compatibility and departure-sample coverage.",
    "Interpolation of missing times, frequency-based or flexible services.",
    "Transfer rules, shapes, pathways and other GTFS fields outside this audit.",
    "Street networks, stop coordinates, station access and accessibility.",
    "Actual journeys, travel-time estimates and observed service performance.",
]


def _read_small_tables(archive: ZipFile) -> dict[str, pd.DataFrame]:
    """Reject ambiguous CSV rather than letting pandas infer or rename fields."""
    tables = {}
    for name in TABLE_NAMES:
        if name not in archive.namelist() and name in {"calendar.txt", "calendar_dates.txt"}:
            tables[name] = pd.DataFrame(columns=sorted(REQUIRED_COLUMNS[name]), dtype="string")
            continue
        require(archive.namelist().count(name) == 1, f"Missing required table: {name}.")
        with archive.open(name) as binary, io.TextIOWrapper(
            binary, encoding="utf-8-sig", newline=""
        ) as text:
            reader = csv.reader(text, strict=True)
            header = next(reader, None)
            require(bool(header), f"{name}: missing header.")
            require(len(header) == len(set(header)), f"{name}: duplicate header column.")
            require(all(field and field == field.strip() for field in header),
                    f"{name}: blank or padded header column.")
            require(not any(any(char in field for char in "\t\r\n") for field in header),
                    f"{name}: forbidden control character in header.")
            require(REQUIRED_COLUMNS[name].issubset(header),
                    f"{name}: missing fields required by the reviewed snapshot contract.")
            rows = []
            for record in reader:
                if not record:
                    continue
                require(len(record) == len(header),
                        f"{name}: wrong field count at physical line {reader.line_num}.")
                require(not any(any(char in value for char in "\t\r\n") for value in record),
                        f"{name}: forbidden control character at physical line {reader.line_num}.")
                rows.append(record)
        tables[name] = pd.DataFrame(rows, columns=header, dtype="string")
    return tables


def _identity_context(tables: dict[str, pd.DataFrame]) -> tuple[dict, dict]:
    stops, agencies, routes = (tables[name] for name in ("stops.txt", "agency.txt", "routes.txt"))
    require_key(stops, ["stop_id"], "stops")
    require(stops.location_type.isin(["", "0", "1", "2", "3", "4"]).all(),
            "stops: invalid location_type.")
    # A single agency may omit its ID, and routes may inherit that sole agency.
    require(not agencies.empty and not agencies.agency_id.duplicated().any(),
            "agency: empty table or duplicate agency_id.")
    require(agencies.agency_id.eq(agencies.agency_id.str.strip()).all(),
            "agency: padded agency_id.")
    if len(agencies) > 1:
        require(agencies.agency_id.ne("").all(), "agency: IDs required for multiple agencies.")
    referenced = routes.agency_id
    require((referenced.isin(agencies.agency_id) |
             (referenced.eq("") & (len(agencies) == 1))).all(),
            "routes: unknown or ambiguous agency reference.")
    for column in ("continuous_pickup", "continuous_drop_off"):
        if column in routes:
            require(routes[column].isin(["", "0", "1", "2", "3"]).all(),
                    f"routes: invalid {column}.")
    route_defaults = {
        str(row.route_id): (str(getattr(row, "continuous_pickup", "")),
                            str(getattr(row, "continuous_drop_off", "")))
        for row in routes.itertuples(index=False)
    }
    defaults = {str(row.trip_id): route_defaults[str(row.route_id)]
                for row in tables["trips.txt"].itertuples(index=False)}
    return dict(zip(stops.stop_id, stops.location_type)), defaults


@contextmanager
def _nested_feed(path: Path, feed_id: str, workspace: Path):
    """Spool one reviewed nested member; never interpret its names as paths."""
    member = f"{feed_id}/google_transit.zip"
    with ZipFile(path) as outer, SpooledTemporaryFile(
        max_size=16 * 1024 * 1024, mode="w+b", dir=workspace
    ) as spool:
        require(outer.namelist().count(member) == 1, f"Missing or duplicate feed: {feed_id}.")
        with outer.open(member) as source:
            shutil.copyfileobj(source, spool, length=1024 * 1024)
        spool.seek(0)
        with ZipFile(spool) as inner:
            names = inner.namelist()
            require(len(names) == len(set(names)), f"Feed {feed_id}: duplicate inner ZIP member.")
            yield inner


def _audit_feed(path: Path, feed_id: str, snapshot: dict, workspace: Path,
                progress: Callable[[str], None]) -> dict:
    progress(f"Feed {feed_id}: reading small tables and calendar exceptions.")
    with _nested_feed(path, feed_id, workspace) as archive:
        tables = _read_small_tables(archive)
        selected, counts = build_active_trips({feed_id: tables}, date.fromisoformat(snapshot["service_date"]))
        active = int(counts.iloc[0]["active_trip_records"])
        replacements = int(counts.iloc[0]["labelled_replacement_trip_records"])
        require(active == snapshot["active_trip_counts"][feed_id],
                f"Feed {feed_id}: active-trip count differs from the snapshot.")
        require(replacements == snapshot["replacement_trip_counts"][feed_id],
                f"Feed {feed_id}: labelled-replacement count differs from the snapshot.")
        stop_types, continuous_defaults = _identity_context(tables)
        require(len(stop_types) == snapshot["location_counts"][feed_id],
                f"Feed {feed_id}: location count differs from the snapshot.")
        platforms = sum(value in {"", "0"} for value in stop_types.values())
        require(platforms == snapshot["platform_counts"][feed_id],
                f"Feed {feed_id}: platform count differs from the snapshot.")
        require(archive.namelist().count("stop_times.txt") == 1,
                f"Feed {feed_id}: missing stop_times.txt.")
        progress(f"Feed {feed_id}: scanning every stop-time row; expected {snapshot['scan_rows'][feed_id]:,}.")
        with archive.open("stop_times.txt") as binary, io.TextIOWrapper(
            binary, encoding="utf-8-sig", newline=""
        ) as text:
            result = audit_stop_times(
                text, trip_ids=set(tables["trips.txt"].trip_id),
                active_trip_ids=set(selected.trip_id), stop_types=stop_types,
                continuous_defaults=continuous_defaults, workspace=workspace,
                expected_rows=snapshot["scan_rows"][feed_id],
                progress=lambda message: progress(f"Feed {feed_id}: {message}"),
            )
        if "frequencies.txt" in archive.namelist():
            result["issues"].append({
                "code": "unsupported_frequency_table", "severity": "blocked", "count": 1,
                "examples": [{"table": "frequencies.txt"}],
            })
            if result["status"] == "passed":
                result["status"] = "blocked"
        result.update(feed_id=feed_id, active_trip_records=active,
                      labelled_replacement_trip_records=replacements,
                      defined_trip_records=len(tables["trips.txt"]),
                      defined_location_records=len(stop_types))
        return result


def audit_routing_timetable(project_root: Path, *, work_root: Path | None = None,
                            progress: Callable[[str], None] | None = None) -> dict:
    """Audit all selected source rows without modifying project files.

    A passed result covers the implemented timetable checks only. Missing raw
    input or unsupported/incomplete semantics returns blocked. Known violated
    input contracts return invalid; operational I/O failures return error.
    """
    emit = progress if progress is not None else lambda message: None
    report = {
        "schema_version": 1, "stage": "gtfs_timetable_audit", "status": "blocked",
        "routing_ready": False, "scan_complete": False, "feeds": [], "errors": [],
        "blockers": [], "not_validated": list(NOT_VALIDATED),
        "project_files_written": 0, "journeys_computed": 0,
        "temporary_workspace_created": False, "temporary_workspace_removed": True,
        "protected_inputs_unchanged": None,
    }
    protected: dict[Path, str] = {}
    temporary_path = None
    current_feed = None
    try:
        root = Path(project_root).resolve()
        config_path = _project_path(root, PILOT_CONFIG_PATH, "pilot configuration")
        protected[config_path] = sha256_file(config_path)
        root, config, snapshot, snapshot_path = _load_inputs(root)
        protected[snapshot_path] = sha256_file(snapshot_path)
        require(load_transport_snapshot(snapshot_path) == snapshot,
                "Snapshot changed while loading the audit contract.")
        report.update(pilot_id=config["pilot_id"], service_date=config["service_date"],
                      timezone=config["timezone"], feed_ids=config["feed_ids"],
                      gtfs_path=config["gtfs_path"], expected_sha256=snapshot["sha256"],
                      config_sha256=protected[config_path], snapshot_sha256=protected[snapshot_path],
                      expected_rows=snapshot["expected_totals"]["source_rows"],
                      expected_active_rows=snapshot["expected_totals"]["active_events"])
        path = _project_path(root, config["gtfs_path"], "gtfs_path")
        if not path.exists():
            report["blockers"].append("The pinned local GTFS archive is missing.")
        else:
            require(path.is_file(), "GTFS input is not a regular file.")
            emit("Hashing the pinned GTFS archive before reading.")
            digest = sha256_file(path)
            report["actual_sha256"] = digest
            protected[path] = digest
            require(digest == snapshot["sha256"], "GTFS fingerprint differs from the audited snapshot.")
            with ZipFile(path) as outer:
                names = outer.namelist()
                require(len(names) == len(set(names)), "Duplicate outer ZIP member.")
                require(set(names) == set(snapshot["outer_members"]), "GTFS outer archive inventory differs.")
            base = Path(work_root if work_root is not None else gettempdir()).resolve()
            require(base.is_dir(), "Temporary work root must be an existing directory.")
            require(not base.is_relative_to(root), "Temporary work root must be outside the project directory.")
            with TemporaryDirectory(prefix="homereach-timetable-", dir=base) as directory:
                temporary_path = Path(directory)
                report["temporary_workspace_created"] = True
                for feed_id in config["feed_ids"]:
                    current_feed = feed_id
                    report["feeds"].append(_audit_feed(path, feed_id, snapshot, temporary_path, emit))
                current_feed = None
            report["rows_scanned"] = sum(feed["rows_scanned"] for feed in report["feeds"])
            report["active_rows_scanned"] = sum(feed["active_rows_scanned"] for feed in report["feeds"])
            report["scan_complete"] = all(feed["scan_complete"] for feed in report["feeds"])
            if report["rows_scanned"] != report["expected_rows"]:
                report["errors"].append("Total source row count differs from the audited snapshot.")
            if report["active_rows_scanned"] != report["expected_active_rows"]:
                report["errors"].append("Total active stop-time row count differs from the audited snapshot.")
            statuses = {feed["status"] for feed in report["feeds"]}
            if statuses - {"passed", "blocked", "invalid"}:
                report["status"] = "error"
                report["errors"].append("A feed audit returned an unexpected or operational-error status.")
            elif report["errors"] or "invalid" in statuses:
                report["status"] = "invalid"
            elif "blocked" in statuses or not report["scan_complete"]:
                report["status"] = "blocked"
            else:
                report["status"] = "passed"
    except (ValueError, BadZipFile, UnicodeError, csv.Error) as error:
        report["status"] = "invalid"
        report["errors"].append(f"Feed {current_feed}: {error}" if current_feed else str(error))
    except (OSError, sqlite3.Error) as error:
        report["status"] = "error"
        report["errors"].append(f"Audit could not complete: {error}")
    except (KeyError, AssertionError) as error:
        report["status"] = "error"
        report["errors"].append(f"Internal timetable processing failed ({type(error).__name__}): {error}")
    finally:
        if temporary_path is not None:
            report["temporary_workspace_removed"] = not temporary_path.exists()
            if not report["temporary_workspace_removed"]:
                report["status"] = "error"
                report["errors"].append("Temporary workspace cleanup did not complete.")
        if protected:
            emit("Verifying protected input fingerprints after the audit.")
            try:
                unchanged = all(path.is_file() and sha256_file(path) == digest
                                for path, digest in protected.items())
            except OSError as error:
                report["status"] = "error"
                report["errors"].append(f"Cannot recheck protected inputs: {error}")
            else:
                report["protected_inputs_unchanged"] = unchanged
                if not unchanged:
                    report["status"] = "invalid"
                    report["errors"].append("A protected input changed during the audit.")
    return report
