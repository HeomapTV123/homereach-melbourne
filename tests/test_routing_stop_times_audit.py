"""Hand-authored stop-time fixtures exercise the audit without Melbourne data."""
from __future__ import annotations

import builtins
import csv
import io
import json
import socket

import pytest

from homereach.routing import stop_times_audit as audit


COLUMNS = (
    "trip_id", "stop_id", "stop_sequence", "arrival_time", "departure_time",
    "pickup_type", "drop_off_type", "timepoint",
)


def stop_time(trip="t1", sequence="0", stop="a", arrival="08:00:00",
              departure=None, **extra):
    return {
        "trip_id": trip, "stop_id": stop, "stop_sequence": str(sequence),
        "arrival_time": arrival,
        "departure_time": arrival if departure is None else departure,
        "pickup_type": "", "drop_off_type": "", "timepoint": "",
        **extra,
    }


def ordinary_trip(trip="t1"):
    return [stop_time(trip), stop_time(trip, "10", "b", "08:10:00")]


def as_csv(rows, columns=COLUMNS):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([row.get(column, "") for column in columns])
    return stream.getvalue()


def issue(report, code):
    found = [row for row in report["issues"] if row["code"] == code]
    assert len(found) == 1, (code, report["issues"])
    return found[0]


def issue_codes(report):
    return {row["code"] for row in report["issues"]}


@pytest.fixture(autouse=True)
def prohibit_runtime_and_network(monkeypatch):
    """A timetable audit has no reason to use a route engine or remote source."""
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.split(".")[0] in {"r5py", "jpype", "jnius", "geopandas"}:
            raise AssertionError("Stop-time audit imported an unnecessary runtime.")
        return original_import(name, *args, **kwargs)

    def prohibited(*args, **kwargs):
        raise AssertionError("Stop-time audit attempted network access.")

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(socket, "create_connection", prohibited)
    monkeypatch.setattr(socket.socket, "connect", prohibited)


def run_audit(tmp_path, rows, *, columns=COLUMNS, trip_ids=None,
              active_trip_ids=None, stop_types=None, **options):
    workspace = tmp_path / "scratch"
    workspace.mkdir(exist_ok=True)
    raw = as_csv(rows, columns)
    text = io.StringIO(raw, newline="")
    report = audit.audit_stop_times(
        text,
        trip_ids={"t1"} if trip_ids is None else set(trip_ids),
        active_trip_ids={"t1"} if active_trip_ids is None else set(active_trip_ids),
        stop_types={"a": "0", "b": ""} if stop_types is None else stop_types,
        workspace=workspace,
        **options,
    )
    assert text.getvalue() == raw
    assert list(workspace.iterdir()) == [], "The audit left temporary database files."
    assert report["scan_complete"] is True
    json.dumps(report, allow_nan=False)
    return report


def test_logical_order_interleaving_extended_times_and_active_scope(tmp_path):
    # Physical order is deliberately unrelated to numeric trip-stop order.
    rows = [
        stop_time("night", "20", "b", "25:05:00"),
        stop_time("day", "3", "b", "8:02:00"),
        stop_time("inactive", "9", "a", "26:10:00"),
        stop_time("night", "0", "a", "24:55:00"),
        stop_time("day", "0", "a", "8:00:00"),
        stop_time("inactive", "0", "a", "26:00:00"),
    ]
    report = run_audit(
        tmp_path, rows, trip_ids={"night", "day", "inactive", "unused"},
        active_trip_ids={"night", "day"}, expected_rows=6,
    )
    assert report["status"] == "passed"
    assert report["rows_scanned"] == 6
    assert report["active_rows_scanned"] == 4
    assert report["known_trips_with_rows"] == 3
    assert report["active_trips_with_rows"] == 2
    assert report["rows_with_extended_times"] == 4
    assert report["active_rows_with_extended_times"] == 2
    assert report["minimum_time_seconds"] == 8 * 3600
    assert report["maximum_time_seconds"] == 26 * 3600 + 10 * 60
    assert issue(report, "unused_trip")["severity"] == "info"
    assert "chronology_reversal" not in issue_codes(report)


def test_repeated_stop_and_nonconsecutive_zero_sequence_are_valid(tmp_path):
    rows = [stop_time(sequence="0", stop="a"),
            stop_time(sequence="14", stop="a", arrival="08:02:00")]
    report = run_audit(tmp_path, rows)
    assert report["status"] == "passed"
    assert report["known_trips_with_rows"] == 1


def test_optional_pickup_dropoff_and_timepoint_columns_may_be_absent(tmp_path):
    required = tuple(column for column in COLUMNS
                     if column not in {"pickup_type", "drop_off_type", "timepoint"})
    report = run_audit(tmp_path, ordinary_trip(), columns=required)
    assert report["status"] == "passed"
    assert report["rows_scanned"] == 2


def test_numeric_equivalent_duplicates_across_batches_are_counted_and_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "BATCH_SIZE", 2)
    rows = ordinary_trip() + [stop_time(sequence="00") for _ in range(17)]
    report = run_audit(tmp_path, rows, expected_rows=19)
    duplicate = issue(report, "duplicate_trip_sequence")
    assert report["status"] == "invalid"
    assert report["rows_scanned"] == 19
    assert duplicate["severity"] == "error"
    assert duplicate["count"] == 17
    assert 0 < len(duplicate["examples"]) <= audit.EXAMPLE_LIMIT < 17


@pytest.mark.parametrize("sequence", ["", "-1", "1.0", "+1", " 1", "one"])
def test_malformed_sequence_is_invalid(tmp_path, sequence):
    rows = ordinary_trip()
    rows[0]["stop_sequence"] = sequence
    report = run_audit(tmp_path, rows)
    assert report["status"] == "invalid"
    assert issue(report, "invalid_stop_sequence")["count"] == 1


def test_sequence_beyond_storage_range_is_explicitly_unsupported(tmp_path):
    rows = ordinary_trip()
    rows[1]["stop_sequence"] = str(2**80)
    report = run_audit(tmp_path, rows)
    assert report["status"] == "blocked"
    assert issue(report, "stop_sequence_out_of_range")["severity"] == "blocked"


@pytest.mark.parametrize("clock", ["24:00:00", "25:01:00", "100:00:00"])
def test_extended_service_day_times_are_preserved(tmp_path, clock):
    rows = [stop_time(arrival=clock), stop_time(sequence="1", stop="b", arrival=clock)]
    report = run_audit(tmp_path, rows)
    hour, minute, second = map(int, clock.split(":"))
    expected = hour * 3600 + minute * 60 + second
    assert report["status"] == "passed"
    assert report["minimum_time_seconds"] == expected
    assert report["maximum_time_seconds"] == expected
    assert report["rows_with_extended_times"] == 2


def test_midnight_is_not_silently_wrapped_into_the_next_day(tmp_path):
    rows = [stop_time(arrival="23:59:00"),
            stop_time(sequence="1", stop="b", arrival="00:01:00")]
    report = run_audit(tmp_path, rows)
    assert report["status"] == "invalid"
    assert issue(report, "chronology_reversal")["count"] == 1


def test_a_stop_dwell_can_cross_midnight_with_extended_departure_time(tmp_path):
    rows = [stop_time(arrival="23:59:00", departure="24:00:00"),
            stop_time(sequence="1", stop="b", arrival="24:10:00")]
    report = run_audit(tmp_path, rows)
    assert report["status"] == "passed"
    assert report["rows_with_extended_times"] == 2
    assert report["minimum_time_seconds"] == 23 * 3600 + 59 * 60
    assert report["maximum_time_seconds"] == 24 * 3600 + 10 * 60


@pytest.mark.parametrize("clock", ["08:60:00", "08:00:60", "-1:00:00", "8:0:00", "08:00", " 08:00:00"])
def test_malformed_time_is_invalid(tmp_path, clock):
    rows = ordinary_trip()
    rows[0]["arrival_time"] = clock
    report = run_audit(tmp_path, rows)
    assert report["status"] == "invalid"
    assert issue(report, "invalid_arrival_time")["count"] == 1


def test_departure_time_is_parsed_independently(tmp_path):
    rows = ordinary_trip()
    rows[0]["departure_time"] = "08:00:60"
    report = run_audit(tmp_path, rows)
    assert report["status"] == "invalid"
    assert issue(report, "invalid_departure_time")["count"] == 1


def test_time_beyond_storage_range_is_not_relabelled_as_bad_syntax(tmp_path):
    clock = "10000000000000000:00:00"
    rows = [stop_time(arrival=clock), stop_time(sequence="1", stop="b", arrival=clock)]
    report = run_audit(tmp_path, rows)
    assert report["status"] == "blocked"
    assert issue(report, "time_out_of_range")["severity"] == "blocked"
    assert "invalid_arrival_time" not in issue_codes(report)


@pytest.mark.parametrize("timepoint", [None, "", "0"])
def test_untimed_interior_is_blocked_without_being_called_invalid(tmp_path, timepoint):
    rows = [stop_time(), stop_time(sequence="5", arrival="", timepoint=timepoint or ""),
            stop_time(sequence="10", stop="b", arrival="08:10:00")]
    columns = tuple(c for c in COLUMNS if c != "timepoint") if timepoint is None else COLUMNS
    report = run_audit(tmp_path, rows, columns=columns)
    assert report["status"] == "blocked"
    assert issue(report, "unresolved_times")["count"] == 1
    assert not any(row["severity"] == "error" for row in report["issues"])


def test_explicit_timepoint_requires_times(tmp_path):
    rows = [stop_time(), stop_time(sequence="5", arrival="", timepoint="1"),
            stop_time(sequence="10", stop="b", arrival="08:10:00")]
    report = run_audit(tmp_path, rows)
    assert report["status"] == "invalid"
    assert issue(report, "missing_timepoint_times")["count"] == 1


@pytest.mark.parametrize("field", ["arrival_time", "departure_time"])
def test_one_sided_interior_time_is_invalid(tmp_path, field):
    rows = [stop_time(), stop_time(sequence="5", arrival="08:05:00", timepoint="0"),
            stop_time(sequence="10", stop="b", arrival="08:10:00")]
    rows[1][field] = ""
    report = run_audit(tmp_path, rows)
    assert report["status"] == "invalid"
    assert issue(report, "unpaired_times")["count"] == 1


@pytest.mark.parametrize("edge", [0, 1])
def test_first_and_last_trip_rows_need_times(tmp_path, edge):
    rows = ordinary_trip()
    rows[edge].update(arrival_time="", departure_time="", timepoint="0")
    # Reverse source order so physical first/last cannot supply this check.
    report = run_audit(tmp_path, rows[::-1])
    assert report["status"] == "invalid"
    assert issue(report, "missing_trip_edge_times")["count"] >= 1


def test_known_chronology_is_checked_across_an_untimed_interior(tmp_path):
    rows = [stop_time(arrival="08:00:00", departure="08:10:00"),
            stop_time(sequence="5", arrival="", timepoint="0"),
            stop_time(sequence="10", stop="b", arrival="08:09:00")]
    report = run_audit(tmp_path, rows[::-1])
    assert report["status"] == "invalid"
    assert issue(report, "chronology_reversal")["count"] == 1
    assert issue(report, "unresolved_times")["severity"] == "blocked"


def test_departure_before_same_stop_arrival_is_invalid(tmp_path):
    rows = ordinary_trip()
    rows[0].update(arrival_time="08:01:00", departure_time="08:00:00")
    report = run_audit(tmp_path, rows)
    assert report["status"] == "invalid"
    assert issue(report, "departure_before_arrival")["count"] == 1


def test_inactive_rows_are_still_audited(tmp_path):
    rows = ordinary_trip() + ordinary_trip("inactive")
    rows[-1]["arrival_time"] = "08:60:00"
    report = run_audit(tmp_path, rows, trip_ids={"t1", "inactive"})
    assert report["rows_scanned"] == 4
    assert report["active_rows_scanned"] == 2
    assert report["status"] == "invalid"
    assert issue(report, "invalid_arrival_time")["count"] == 1


@pytest.mark.parametrize("field,value,code", [
    ("trip_id", "unknown", "unknown_trip"),
    ("trip_id", "", "invalid_trip_id"),
    ("trip_id", " t1 ", "invalid_trip_id"),
    ("stop_id", "unknown", "unknown_stop"),
    ("stop_id", "", "invalid_stop_id"),
    ("stop_id", " a ", "invalid_stop_id"),
])
def test_identifiers_are_checked_without_silent_trimming(tmp_path, field, value, code):
    rows = ordinary_trip()
    rows[0][field] = value
    report = run_audit(tmp_path, rows)
    assert report["status"] == "invalid"
    assert issue(report, code)["count"] == 1
    if field == "trip_id":
        assert report["logical_trip_checks_complete"] is False


def test_long_invalid_identifiers_do_not_expand_every_report_example(tmp_path):
    rows = [stop_time(sequence=str(sequence), stop="missing-" + "x" * 500)
            for sequence in range(20)]
    report = run_audit(tmp_path, rows)
    missing = issue(report, "unknown_stop")
    assert report["status"] == "invalid"
    assert missing["count"] == 20
    assert len(missing["examples"]) <= audit.EXAMPLE_LIMIT
    assert all(len(value) <= audit.MAX_EXAMPLE_TEXT
               for example in missing["examples"] for value in example.values()
               if isinstance(value, str))


@pytest.mark.parametrize("location_type", ["1", "2", "3", "4"])
def test_stop_times_cannot_reference_nonboarding_location_types(tmp_path, location_type):
    report = run_audit(tmp_path, ordinary_trip(), stop_types={"a": location_type, "b": "0"})
    assert report["status"] == "invalid"
    assert issue(report, "non_boarding_stop")["count"] == 1


def test_active_missing_or_single_stop_trips_block_readiness(tmp_path):
    report = run_audit(tmp_path, [stop_time()], trip_ids={"t1", "missing"},
                       active_trip_ids={"t1", "missing"})
    assert report["status"] == "blocked"
    assert issue(report, "active_trip_too_short")["count"] == 1
    assert issue(report, "active_trip_without_stop_times")["count"] == 1
    assert not any(row["severity"] == "error" for row in report["issues"])


def test_inactive_unused_and_single_stop_trips_are_informational(tmp_path):
    rows = ordinary_trip() + [stop_time("short")]
    report = run_audit(tmp_path, rows, trip_ids={"t1", "short", "unused"})
    assert report["status"] == "passed"
    assert issue(report, "inactive_trip_too_short")["severity"] == "info"
    assert issue(report, "unused_trip")["count"] == 1


def test_header_only_feed_cannot_pass_with_declared_active_trips(tmp_path):
    report = run_audit(tmp_path, [])
    assert report["rows_scanned"] == 0
    assert report["active_trips_with_rows"] == 0
    assert report["status"] == "blocked"
    assert issue(report, "active_trip_without_stop_times")["count"] == 1


@pytest.mark.parametrize("field", ["pickup_type", "drop_off_type", "timepoint"])
def test_invalid_service_enums_are_reported(tmp_path, field):
    rows = ordinary_trip()
    rows[0][field] = "9"
    report = run_audit(tmp_path, rows)
    assert report["status"] == "invalid"
    assert issue(report, "invalid_" + field)["count"] == 1


@pytest.mark.parametrize("value", ["2", "3"])
def test_arrangement_required_values_are_valid_but_reported(tmp_path, value):
    rows = ordinary_trip()
    rows[0]["pickup_type"] = value
    report = run_audit(tmp_path, rows)
    assert report["status"] == "passed"
    assert issue(report, "arrangement_required")["severity"] == "info"
    assert issue(report, "arrangement_required")["count"] == 1


@pytest.mark.parametrize("field", ["location_id", "location_group_id"])
def test_flexible_locations_are_unsupported_without_false_fixed_stop_errors(tmp_path, field):
    rows = [stop_time(), stop_time(sequence="5", stop="", arrival="", **{field: "area"}),
            stop_time(sequence="10", stop="b", arrival="08:10:00")]
    report = run_audit(tmp_path, rows, columns=(*COLUMNS, field))
    assert report["status"] == "blocked"
    assert issue(report, "unsupported_flexible_service")["count"] == 1
    assert report["logical_trip_checks_complete"] is False
    assert not any(row["severity"] == "error" for row in report["issues"])


def test_blank_flexible_columns_do_not_make_a_fixed_stop_feed_unsupported(tmp_path):
    extras = ("location_id", "location_group_id", "start_pickup_drop_off_window",
              "end_pickup_drop_off_window", "pickup_booking_rule_id", "drop_off_booking_rule_id")
    report = run_audit(tmp_path, ordinary_trip(), columns=(*COLUMNS, *extras))
    assert report["status"] == "passed"
    assert "unsupported_flexible_service" not in issue_codes(report)


@pytest.mark.parametrize("field", ["continuous_pickup", "continuous_drop_off"])
@pytest.mark.parametrize("value", ["0", "2", "3"])
def test_nondefault_continuous_service_is_blocked(tmp_path, field, value):
    rows = ordinary_trip()
    rows[0][field] = value
    report = run_audit(tmp_path, rows, columns=(*COLUMNS, field))
    assert report["status"] == "blocked"
    assert issue(report, "unsupported_continuous_service")["count"] == 1


@pytest.mark.parametrize("field", ["continuous_pickup", "continuous_drop_off"])
def test_invalid_continuous_value_is_an_error(tmp_path, field):
    rows = ordinary_trip()
    rows[0][field] = "9"
    report = run_audit(tmp_path, rows, columns=(*COLUMNS, field))
    assert report["status"] == "invalid"
    assert issue(report, "invalid_" + field)["count"] == 1


@pytest.mark.parametrize("row_override,expected", [("", "blocked"), ("1", "passed")])
def test_stop_time_override_controls_inherited_route_continuous_pickup(tmp_path, row_override, expected):
    rows = ordinary_trip()
    for row in rows:
        row["continuous_pickup"] = row_override
    report = run_audit(tmp_path, rows, columns=(*COLUMNS, "continuous_pickup"),
                       continuous_defaults={"t1": ("0", "1")})
    assert report["status"] == expected
    if expected == "blocked":
        assert issue(report, "unsupported_continuous_service")["count"] == 2
    else:
        assert "unsupported_continuous_service" not in issue_codes(report)


@pytest.mark.parametrize("defaults", [("", ""), ("1", "1")])
def test_default_route_continuous_values_allow_fixed_stop_service(tmp_path, defaults):
    report = run_audit(tmp_path, ordinary_trip(), continuous_defaults={"t1": defaults})
    assert report["status"] == "passed"


def test_row_count_is_reconciled_with_pinned_expected_value(tmp_path):
    report = run_audit(tmp_path, ordinary_trip(), expected_rows=3)
    assert report["rows_scanned"] == 2
    assert report["status"] == "invalid"
    assert issue(report, "row_count_mismatch")["severity"] == "error"


@pytest.mark.parametrize("missing", ["trip_id", "stop_id", "stop_sequence", "arrival_time", "departure_time"])
def test_missing_required_fixed_stop_header_is_fatal(tmp_path, missing):
    workspace = tmp_path / "scratch"
    workspace.mkdir()
    text = io.StringIO(as_csv(ordinary_trip(), tuple(c for c in COLUMNS if c != missing)))
    with pytest.raises(ValueError):
        audit.audit_stop_times(text, trip_ids={"t1"}, active_trip_ids={"t1"},
                               stop_types={"a": "0", "b": "0"}, workspace=workspace)
    assert list(workspace.iterdir()) == []


@pytest.mark.parametrize("columns", [
    (*COLUMNS, "trip_id"), (" trip_id", *COLUMNS[1:]), (*COLUMNS, ""),
    (*COLUMNS, "extra\tfield"),
])
def test_ambiguous_headers_are_rejected(tmp_path, columns):
    workspace = tmp_path / "scratch"
    workspace.mkdir()
    with pytest.raises(ValueError):
        audit.audit_stop_times(io.StringIO(as_csv(ordinary_trip(), columns)),
                               trip_ids={"t1"}, active_trip_ids={"t1"},
                               stop_types={"a": "0", "b": "0"}, workspace=workspace)
    assert list(workspace.iterdir()) == []


def test_bad_width_is_counted_and_later_valid_rows_are_still_read(tmp_path):
    workspace = tmp_path / "scratch"
    workspace.mkdir()
    raw = (as_csv(ordinary_trip()[:1]) + "t1,a,5\n"
           + as_csv(ordinary_trip()[1:]).split("\n", 1)[1])
    report = audit.audit_stop_times(io.StringIO(raw), trip_ids={"t1"}, active_trip_ids={"t1"},
                                    stop_types={"a": "0", "b": "0"}, workspace=workspace,
                                    expected_rows=3)
    assert report["status"] == "invalid"
    assert report["scan_complete"] is True
    assert report["rows_scanned"] == 3
    assert report["maximum_time_seconds"] == 8 * 3600 + 10 * 60
    assert issue(report, "invalid_field_count")["count"] == 1
    assert list(workspace.iterdir()) == []


def test_quoted_multiline_record_has_correct_data_and_physical_line_numbers(tmp_path):
    rows = ordinary_trip()
    rows[1]["stop_id"] = "unknown\nstop"
    report = run_audit(tmp_path, rows)
    example = issue(report, "unknown_stop")["examples"][0]
    assert report["rows_scanned"] == 2
    assert example["data_row"] == 2
    assert example["line_end"] == 4
    assert issue(report, "forbidden_field_characters")["count"] == 1


@pytest.mark.parametrize("character", ["\t", "\r", "\n"])
def test_gtfs_forbidden_characters_in_extra_columns_are_not_ignored(tmp_path, character):
    rows = ordinary_trip()
    rows[0]["unused_extra"] = "before" + character + "after"
    report = run_audit(tmp_path, rows, columns=(*COLUMNS, "unused_extra"))
    assert report["status"] == "invalid"
    assert issue(report, "forbidden_field_characters")["count"] == 1


def test_unrecoverable_csv_error_cleans_up_after_a_completed_batch(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "BATCH_SIZE", 2)
    workspace = tmp_path / "scratch"
    workspace.mkdir()
    raw = as_csv(ordinary_trip()) + '"unfinished quoted field\n'
    with pytest.raises(ValueError):
        audit.audit_stop_times(io.StringIO(raw), trip_ids={"t1"}, active_trip_ids={"t1"},
                               stop_types={"a": "0", "b": "0"}, workspace=workspace)
    assert list(workspace.iterdir()) == []


def test_input_read_failure_cleans_only_owned_temporary_files(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "BATCH_SIZE", 2)
    workspace = tmp_path / "scratch"
    workspace.mkdir()
    sentinel = workspace / "keep.txt"
    sentinel.write_text("caller-owned", encoding="utf-8")

    class FailingText(io.StringIO):
        calls = 0

        def __next__(self):
            self.calls += 1
            if self.calls == 4:
                raise OSError("fixture stream stopped")
            return super().__next__()

    with pytest.raises(OSError, match="fixture stream stopped"):
        audit.audit_stop_times(FailingText(as_csv(ordinary_trip())),
                               trip_ids={"t1"}, active_trip_ids={"t1"},
                               stop_types={"a": "0", "b": "0"}, workspace=workspace)
    assert {path.name for path in workspace.iterdir()} == {"keep.txt"}
    assert sentinel.read_text(encoding="utf-8") == "caller-owned"


def test_progress_is_available_without_writing_to_source(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "PROGRESS_ROWS", 2)
    messages = []
    report = run_audit(tmp_path, ordinary_trip(), progress=messages.append)
    assert report["status"] == "passed"
    assert messages and all(isinstance(message, str) for message in messages)
