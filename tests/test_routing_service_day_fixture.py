"""Independent service-day fixtures and result checks need no routing runtime."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import csv
from datetime import date, datetime, timedelta
import importlib.util
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
from zipfile import ZIP_STORED, ZipFile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/routing_service_day_fixture.py"
SPEC = importlib.util.spec_from_file_location("routing_service_day_fixture_under_test", SCRIPT)
m = importlib.util.module_from_spec(SPEC)
previous_path = sys.path.copy()
try:
    sys.path.insert(0, str(SCRIPT.parent))
    sys.modules[SPEC.name] = m
    SPEC.loader.exec_module(m)
finally:
    sys.path[:] = previous_path


# Explicit expectations are separate from the module's timetable generator and
# oracle constants. Every overnight case must retain its civil-date rollover.
EXPECTED = {
    "daytime_control": ("2026-10-13T08:00:00", "SD_DAY", "2026-10-13T08:05:00", "2026-10-13T08:10:00"),
    "next_date_daytime_control": ("2026-10-14T09:00:00", "SD_WEDNESDAY", "2026-10-14T09:05:00", "2026-10-14T09:10:00"),
    "daytime_calendar_addition": ("2026-10-13T10:00:00", "SD_ADDED_DAY", "2026-10-13T10:05:00", "2026-10-13T10:10:00"),
    "daytime_calendar_removal": ("2026-10-13T11:00:00", None, None, None),
    "midnight_crossing": ("2026-10-13T23:50:00", "SD_CROSS_MIDNIGHT", "2026-10-13T23:58:00", "2026-10-14T00:03:00"),
    "previous_service_24h": ("2026-10-14T00:10:00", "SD_AFTER_24", "2026-10-14T00:15:00", "2026-10-14T00:20:00"),
    "previous_service_25h": ("2026-10-14T01:00:00", "SD_AFTER_25", "2026-10-14T01:05:00", "2026-10-14T01:10:00"),
    "previous_service_32h": ("2026-10-14T08:37:00", "SD_AFTER_32", "2026-10-14T08:42:00", "2026-10-14T08:47:00"),
    "calendar_addition": ("2026-10-14T02:00:00", "SD_ADDED", "2026-10-14T02:05:00", "2026-10-14T02:10:00"),
    "calendar_removal": ("2026-10-14T03:00:00", None, None, None),
    "same_date_must_not_wrap": ("2026-10-13T01:00:00", None, None, None),
    "inactive_date": ("2026-10-15T01:00:00", None, None, None),
}
POSITIVE_CASES = [identifier for identifier, values in EXPECTED.items() if values[1] is not None]
NEGATIVE_CASES = [identifier for identifier, values in EXPECTED.items() if values[1] is None]
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def case(identifier):
    return deepcopy(next(item for item in m.CASES if item["id"] == identifier))


def tables():
    return {name: list(csv.DictReader(StringIO(value.decode("utf-8"))))
            for name, value in m.gtfs_tables().items()}


def service_active(source, service_id, service_day):
    """Independent small-calendar evaluation for this explicit fixture."""
    key = service_day.strftime("%Y%m%d")
    active = False
    for row in source["calendar.txt"]:
        if row["service_id"] == service_id:
            active = (row["start_date"] <= key <= row["end_date"]
                      and row[WEEKDAYS[service_day.weekday()]] == "1")
    changes = [row for row in source["calendar_dates.txt"]
               if row["service_id"] == service_id and row["date"] == key]
    assert len(changes) <= 1
    if changes:
        active = changes[0]["exception_type"] == "1"
    return active


def seconds(clock):
    hour, minute, second = map(int, clock.split(":"))
    return hour * 3600 + minute * 60 + second


def valid_rows(identifier="daytime_control", *, option=0, offset_seconds=0):
    query, route, departure, arrival = EXPECTED[identifier]
    query = datetime.fromisoformat(query) + timedelta(seconds=offset_seconds)
    bus_departure = datetime.fromisoformat(departure)
    bus_arrival = datetime.fromisoformat(arrival)
    common = {"from_id": "synthetic_origin", "to_id": "synthetic_destination", "option": option,
              "geometry_nonempty": True, "agency_id": None, "route_id": None,
              "start_stop_id": None, "end_stop_id": None}
    return [
        {**common, "segment": 0, "mode": "WALK", "departure_time": query.isoformat(),
         "travel_time_seconds": 12.0, "wait_time_seconds": 0.0, "distance_m": 11.1},
        {**common, "segment": 1, "mode": "BUS", "departure_time": bus_departure.isoformat(),
         "travel_time_seconds": 300.0,
         "wait_time_seconds": (bus_departure - query).total_seconds() - 12.0,
         "distance_m": 2668.678, "agency_id": "SMOKE", "route_id": route,
         "start_stop_id": "SMOKE_WEST", "end_stop_id": "SMOKE_EAST"},
        {**common, "segment": 2, "mode": "WALK",
         "departure_time": (bus_arrival + timedelta(seconds=60)).isoformat(),
         "travel_time_seconds": 12.0, "wait_time_seconds": 0.0, "distance_m": 11.254},
    ]


def failed(rows, identifier="daytime_control", *, selected_case=None):
    original = deepcopy(rows)
    result = m.validate_case(case(identifier) if selected_case is None else selected_case, rows)
    assert result["status"] == "failed"
    assert result["problems"]
    # NaN values do not compare equal, so use a JSON representation for the
    # mutation check while requiring the returned report itself to be finite.
    assert json.dumps(rows, sort_keys=True) == json.dumps(original, sort_keys=True)
    json.dumps(result, allow_nan=False)
    return result


def test_cases_pin_local_dates_independently_of_gtfs_clock_serialization():
    assert len(m.CASES) == 12
    assert {item["id"] for item in m.CASES} == set(EXPECTED)
    for item in m.CASES:
        observed = tuple(item[key] for key in (
            "departure", "expected_route_id", "expected_bus_departure", "expected_bus_arrival"))
        assert observed == EXPECTED[item["id"]]
        assert item["description"]
    assert m.TIMEZONE == "Australia/Melbourne"
    assert m.QUERY_WINDOW_SECONDS == 360


def test_fixture_preserves_reviewed_stops_shape_and_streets():
    import routing_smoke_fixture as original
    current = m.gtfs_tables()
    assert current["stops.txt"] == original.gtfs_tables()["stops.txt"]
    assert current["shapes.txt"] == original.gtfs_tables()["shapes.txt"]
    if hasattr(m, "street_xml"):
        assert m.street_xml() == original.street_xml()
    assert tables()["agency.txt"][0]["agency_timezone"] == "Australia/Melbourne"


def test_source_tables_are_self_contained_and_use_only_expected_semantics():
    source = tables()
    assert set(source) == {"agency.txt", "stops.txt", "routes.txt", "trips.txt", "stop_times.txt",
                           "calendar.txt", "calendar_dates.txt", "shapes.txt", "feed_info.txt"}
    assert {row["agency_id"] for row in source["agency.txt"]} == {"SMOKE"}
    assert {row["stop_id"] for row in source["stops.txt"]} == {"SMOKE_WEST", "SMOKE_EAST"}
    routes = {row["route_id"] for row in source["routes.txt"]}
    assert routes == {values[1] for values in EXPECTED.values() if values[1]} | {"SD_REMOVED", "SD_REMOVED_DAY"}
    assert len(source["routes.txt"]) == len(routes) == 10
    trips = {row["trip_id"]: row for row in source["trips.txt"]}
    assert len(trips) == len(source["trips.txt"]) == 10
    services = {row["service_id"] for row in source["calendar.txt"]}
    shapes = {row["shape_id"] for row in source["shapes.txt"]}
    for row in source["routes.txt"]:
        assert row["route_type"] == "3"
        assert row["agency_id"] == "SMOKE"
    for row in trips.values():
        assert row["route_id"] in routes
        assert row["service_id"] in services
        assert row["shape_id"] in shapes
    assert len(source["stop_times.txt"]) == 20
    assert all(row["trip_id"] in trips for row in source["stop_times.txt"])


def test_service_day_seconds_and_calendar_exceptions_yield_the_intended_civil_dates():
    source = tables()
    trips = {row["trip_id"]: row for row in source["trips.txt"]}
    records = defaultdict(list)
    for row in source["stop_times.txt"]:
        records[trips[row["trip_id"]]["route_id"]].append(row)
    expected_clocks = {
        "SD_DAY": ("08:05:00", "08:10:00"),
        "SD_WEDNESDAY": ("09:05:00", "09:10:00"),
        "SD_ADDED_DAY": ("10:05:00", "10:10:00"),
        "SD_REMOVED_DAY": ("11:05:00", "11:10:00"),
        "SD_CROSS_MIDNIGHT": ("23:58:00", "24:03:00"),
        "SD_AFTER_24": ("24:15:00", "24:20:00"),
        "SD_AFTER_25": ("25:05:00", "25:10:00"),
        "SD_AFTER_32": ("32:42:00", "32:47:00"),
        "SD_ADDED": ("26:05:00", "26:10:00"),
        "SD_REMOVED": ("27:05:00", "27:10:00"),
    }
    for route, rows in records.items():
        rows.sort(key=lambda row: int(row["stop_sequence"]))
        assert [row["stop_id"] for row in rows] == ["SMOKE_WEST", "SMOKE_EAST"]
        assert [int(row["stop_sequence"]) for row in rows] == [1, 2]
        assert tuple(row["departure_time"] for row in rows) == expected_clocks[route]
        assert all(row["arrival_time"] == row["departure_time"] for row in rows)
        assert seconds(rows[1]["arrival_time"]) - seconds(rows[0]["departure_time"]) == 300
    for identifier in POSITIVE_CASES:
        _, route, expected_departure, expected_arrival = EXPECTED[identifier]
        rows = records[route]
        service_day = date(2026, 10, 14) if route == "SD_WEDNESDAY" else date(2026, 10, 13)
        trip = trips[rows[0]["trip_id"]]
        assert service_active(source, trip["service_id"], service_day)
        start = datetime.combine(service_day, datetime.min.time())
        assert (start + timedelta(seconds=seconds(rows[0]["departure_time"]))).isoformat() == expected_departure
        assert (start + timedelta(seconds=seconds(rows[1]["arrival_time"]))).isoformat() == expected_arrival
    removed_service = trips[records["SD_REMOVED"][0]["trip_id"]]["service_id"]
    added_service = trips[records["SD_ADDED"][0]["trip_id"]]["service_id"]
    assert not service_active(source, removed_service, date(2026, 10, 13))
    assert not service_active(source, added_service, date(2026, 10, 14))
    assert all(not service_active(source, service, date(2026, 10, 15))
               for service in {row["service_id"] for row in source["calendar.txt"]})


def test_same_day_controls_isolate_addition_and_removal_from_overnight_handling():
    source = tables()
    services = {row["route_id"]: row["service_id"] for row in source["trips.txt"]}
    assert services["SD_ADDED_DAY"] == services["SD_ADDED"] == "SD_ADDED"
    assert services["SD_REMOVED_DAY"] == services["SD_REMOVED"] == "SD_REMOVED"
    ordinary_calendar = {**source, "calendar_dates.txt": []}
    service_day = date(2026, 10, 13)
    assert not service_active(ordinary_calendar, "SD_ADDED", service_day)
    assert service_active(source, "SD_ADDED", service_day)
    assert service_active(ordinary_calendar, "SD_REMOVED", service_day)
    assert not service_active(source, "SD_REMOVED", service_day)


def test_zip_is_deterministic_complete_and_never_replaces_existing_evidence(tmp_path):
    first, second = tmp_path / "first.zip", tmp_path / "second.zip"
    m.write_gtfs(first)
    m.write_gtfs(second)
    assert first.read_bytes() == second.read_bytes()
    with ZipFile(first) as archive:
        assert len(archive.namelist()) == len(set(archive.namelist())) == 9
        assert set(archive.namelist()) == set(m.gtfs_tables())
        for item in archive.infolist():
            assert item.date_time == (2026, 1, 1, 0, 0, 0)
            assert item.compress_type == ZIP_STORED
            assert archive.read(item.filename) == m.gtfs_tables()[item.filename]
        assert archive.testzip() is None
    before = first.read_bytes()
    with pytest.raises(FileExistsError):
        m.write_gtfs(first)
    assert first.read_bytes() == before


@pytest.mark.parametrize("identifier", POSITIVE_CASES)
def test_complete_expected_itinerary_passes_without_modifying_returned_rows(identifier):
    rows = valid_rows(identifier)
    before = deepcopy(rows)
    result = m.validate_case(case(identifier), rows)
    assert result["status"] == "passed", result
    assert result["problems"] == []
    assert result["options_checked"] == result["bus_legs_checked"] == 1
    assert rows == before
    json.dumps(result, allow_nan=False)


def test_variable_option_count_sparse_ids_and_shuffled_rows_do_not_change_acceptance():
    rows = valid_rows(option=2) + valid_rows(option=19, offset_seconds=30)
    rows.reverse()
    result = m.validate_case(case("daytime_control"), rows)
    assert result["status"] == "passed", result
    assert result["options_checked"] == 2
    assert result["bus_legs_checked"] == 2


@pytest.mark.parametrize("identifier", NEGATIVE_CASES)
def test_no_service_controls_require_empty_results(identifier):
    result = m.validate_case(case(identifier), [])
    assert result["status"] == "passed"
    assert result["options_checked"] == result["bus_legs_checked"] == 0
    failed(valid_rows(), identifier)
    failed([valid_rows()[0]], identifier)


@pytest.mark.parametrize("identifier", POSITIVE_CASES)
def test_empty_or_walking_only_results_cannot_satisfy_positive_service_cases(identifier):
    failed([], identifier)
    failed([valid_rows(identifier)[0]], identifier)


@pytest.mark.parametrize("identifier", ["midnight_crossing", "previous_service_24h", "previous_service_25h", "previous_service_32h", "calendar_addition"])
def test_overnight_bus_on_wrong_civil_day_is_rejected(identifier):
    rows = valid_rows(identifier)
    rows[1]["departure_time"] = (datetime.fromisoformat(rows[1]["departure_time"]) - timedelta(days=1)).isoformat()
    failed(rows, identifier)


@pytest.mark.parametrize("row_index,key,value", [
    (1, "agency_id", "WRONG"), (1, "route_id", "WRONG"),
    (1, "start_stop_id", "SMOKE_EAST"), (1, "end_stop_id", "SMOKE_WEST"),
    (0, "from_id", "unreviewed_origin"), (2, "to_id", "unreviewed_destination"),
    (1, "mode", "TRAM"), (0, "mode", "BUS"), (2, "mode", "CAR"),
    (1, "segment", 0), (1, "option", 1), (2, "segment", 3),
    (0, "option", True), (0, "segment", False), (0, "option", -1),
    (1, "travel_time_seconds", 299), (1, "wait_time_seconds", 0),
    (0, "wait_time_seconds", 5), (2, "wait_time_seconds", 60),
    (1, "geometry_nonempty", False), (2, "geometry_nonempty", 1),
])
def test_identity_sequence_duration_wait_and_geometry_mutations_fail(row_index, key, value):
    rows = valid_rows()
    rows[row_index][key] = value
    failed(rows)


@pytest.mark.parametrize("row_index,key,value", [
    (0, "travel_time_seconds", True), (1, "travel_time_seconds", float("nan")),
    (2, "travel_time_seconds", float("inf")), (0, "distance_m", float("-inf")),
    (1, "distance_m", "2668.678"), (2, "distance_m", None), (0, "distance_m", 0),
    (1, "wait_time_seconds", float("nan")), (1, "wait_time_seconds", True),
    (2, "wait_time_seconds", -1),
])
def test_malformed_numeric_observations_are_serializable_failures(row_index, key, value):
    rows = valid_rows()
    rows[row_index][key] = value
    failed(rows)


@pytest.mark.parametrize("key", ["route_id", "departure_time", "option", "segment", "transport_mode", "geometry_nonempty"])
def test_required_observation_fields_cannot_be_missing(key):
    rows = valid_rows()
    # The public records schema uses mode, rather than the DataFrame column.
    rows[1].pop("mode" if key == "transport_mode" else key)
    failed(rows)


@pytest.mark.parametrize("value", [None, "not-a-time", "2026-10-13T08:05:00Z", "2026-10-13T08:05:00+11:00", 123])
def test_invalid_or_implicitly_converted_datetime_values_are_rejected(value):
    rows = valid_rows()
    rows[1]["departure_time"] = value
    failed(rows)


@pytest.mark.parametrize("offset", [-1, m.QUERY_WINDOW_SECONDS, m.QUERY_WINDOW_SECONDS + 1])
def test_first_departure_must_belong_to_the_requested_sample_window(offset):
    failed(valid_rows(offset_seconds=offset))


def test_access_overlap_and_incorrect_egress_padding_fail():
    overlap = valid_rows()
    overlap[0]["travel_time_seconds"] = 301
    failed(overlap)
    padding = valid_rows()
    padding[2]["departure_time"] = "2026-10-13T08:10:00"
    failed(padding)


@pytest.mark.parametrize("rows", [None, {}, "not rows", [None], ["row"], [5], [[]]])
def test_malformed_result_container_never_becomes_a_success(rows):
    failed(rows)


def test_duplicate_segment_rows_and_partial_additional_options_fail():
    rows = valid_rows()
    failed(rows + [deepcopy(rows[1])])
    failed(rows + valid_rows(option=7)[:2])


def test_modified_or_unknown_case_cannot_change_the_expected_schedule():
    selected = case("daytime_control")
    selected["expected_bus_departure"] = "2026-10-13T08:06:00"
    failed(valid_rows(), selected_case=selected)
    selected = case("daytime_control")
    selected["id"] = "unreviewed_case"
    failed(valid_rows(), selected_case=selected)


def test_finding_examples_are_bounded_but_failure_count_is_retained():
    rows = []
    for option in range(100):
        group = valid_rows(option=option)
        group[1]["route_id"] = "WRONG"
        rows.extend(group)
    result = failed(rows)
    assert 1 <= len(result["problems"]) <= 12
    assert result["problem_count"] >= 100


def test_import_and_fixture_generation_do_not_load_engine_or_numeric_libraries():
    bootstrap = """
import importlib.abc, json, runpy, sys
class RejectRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'r5py','jpype','geopandas','rasterio','shapely','numpy','pandas'}:
            raise AssertionError('Unexpected runtime import: ' + fullname)
sys.meta_path.insert(0, RejectRuntime())
sys.path.insert(0, sys.argv[1])
import routing_service_day_fixture as fixture
print(json.dumps({'cases':len(fixture.CASES),'tables':len(fixture.gtfs_tables())}))
"""
    result = subprocess.run([sys.executable, "-B", "-c", bootstrap, str(SCRIPT.parent)],
                            text=True, capture_output=True, timeout=30, check=False,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"cases": 12, "tables": 9}
