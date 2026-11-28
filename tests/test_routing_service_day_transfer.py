"""Independent fixture/calendar/state examples for the native transfer baseline.

The observation helper is hand-declared test data, not a recorded engine result.
It intentionally preserves the missing mixed-day itinerary and the valid
same-day control. It is also reused by process-boundary tests.
"""
from __future__ import annotations

from copy import deepcopy
import csv
from datetime import datetime, timedelta
import hashlib
import importlib.util
from io import StringIO
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "routing_transfer_fixture_under_test", ROOT / "scripts/routing_service_day_transfer.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

IDS = (
    "mixed_day_transfer", "same_day_transfer", "mixed_remove_first", "mixed_remove_second",
    "mixed_impossible_connection", "same_day_remove_first", "same_day_remove_second",
    "same_day_impossible_connection",
)
# Independent test specification: raw first/second times, first weekday,
# removal service/date, and the Wednesday active-service code set.
EXPECTED = {
    "mixed_day_transfer": ((90300, 90600, 4500, 4800), "tuesday", None, [1]),
    "same_day_transfer": ((3900, 4200, 4500, 4800), "wednesday", None, [0, 1]),
    "mixed_remove_first": ((90300, 90600, 4500, 4800), "tuesday", ("TRANSFER_FIRST", "20261013"), [1]),
    "mixed_remove_second": ((90300, 90600, 4500, 4800), "tuesday", ("TRANSFER_SECOND", "20261014"), []),
    "mixed_impossible_connection": ((90300, 90600, 4140, 4440), "tuesday", None, [1]),
    "same_day_remove_first": ((3900, 4200, 4500, 4800), "wednesday", ("TRANSFER_FIRST", "20261014"), [1]),
    "same_day_remove_second": ((3900, 4200, 4500, 4800), "wednesday", ("TRANSFER_SECOND", "20261014"), [0]),
    "same_day_impossible_connection": ((3900, 4200, 4140, 4440), "wednesday", None, [0, 1]),
}
REQUEST = {
    "native_date": "2026-10-14", "from_time": 3600, "to_time": 3960,
    "from_lon": 0.0061, "from_lat": 0.018, "to_lon": 0.0299, "to_lat": 0.018,
    "monte_carlo_draws": 60, "max_trip_duration_minutes": 30, "max_rides": 2,
    "suboptimal_minutes": 5, "walk_speed_mps": 1.0, "reverse_search": False,
    "transit_modes": ["BUS"], "access_modes": ["WALK"], "egress_modes": ["WALK"],
}
STOPS = [
    {"stop_index": 0, "stop_id": "TRANSFER_A", "scoped_stop_id": "test:TRANSFER_A"},
    {"stop_index": 1, "stop_id": "TRANSFER_B", "scoped_stop_id": "test:TRANSFER_B"},
    {"stop_index": 2, "stop_id": "TRANSFER_C", "scoped_stop_id": "test:TRANSFER_C"},
]
SERVICES = [{"service_code": 0, "service_id": "TRANSFER_FIRST"},
            {"service_code": 1, "service_id": "TRANSFER_SECOND"}]


def case_definition(identifier):
    return {"id": identifier, "civil_departure": "2026-10-14T01:00:00",
            "expected_two_bus_path": identifier in {"mixed_day_transfer", "same_day_transfer"}}


def same_day_chain(sample=3600):
    """A hand-calculated valid two-bus chain, including R5's egress round zero."""
    return [
        {"time": sample + 12, "board_time": -1, "pattern": -1, "trip": -1, "round": 0, "stop": 0,
         "board_stop_position": -1, "alight_stop_position": -1, "access_mode": "WALK", "egress_mode": None},
        {"time": 4200, "board_time": 3900, "pattern": 0, "trip": 0, "round": 1, "stop": 1,
         "board_stop_position": 0, "alight_stop_position": 1, "access_mode": "WALK", "egress_mode": None},
        {"time": 4800, "board_time": 4500, "pattern": 1, "trip": 0, "round": 2, "stop": 2,
         "board_stop_position": 0, "alight_stop_position": 1, "access_mode": "WALK", "egress_mode": None},
        {"time": 4812, "board_time": 0, "pattern": -1, "trip": -1, "round": 0, "stop": -1,
         "board_stop_position": 0, "alight_stop_position": 0, "access_mode": "WALK", "egress_mode": "WALK"},
    ]


def valid_baseline_report():
    """Return independently declared observations: seven passes, one real gate failure.

    No mixed-day path is fabricated. Under an unchanged current-date request,
    the raw Tuesday 25-hour trip is inactive; the required civil-time connection
    remains missing. This helper is not evidence of an actual native run.
    """
    cases = []
    for identifier in IDS:
        times, _, _, active = EXPECTED[identifier]
        schedules = [
            {"pattern_index": 0, "trip_index": 0, "route_id": "TRANSFER_ROUTE_AB",
             "scoped_trip_id": "test:TRANSFER_AB", "trip_id": "TRANSFER_AB", "service_code": 0,
             "stop_indices": [0, 1], "stop_ids": ["TRANSFER_A", "TRANSFER_B"],
             "arrivals": list(times[:2]), "departures": list(times[:2]), "frequency_based": False},
            {"pattern_index": 1, "trip_index": 0, "route_id": "TRANSFER_ROUTE_BC",
             "scoped_trip_id": "test:TRANSFER_BC", "trip_id": "TRANSFER_BC", "service_code": 1,
             "stop_indices": [1, 2], "stop_ids": ["TRANSFER_B", "TRANSFER_C"],
             "arrivals": list(times[2:]), "departures": list(times[2:]), "frequency_based": False},
        ]
        original = [
            {"stop_index": 0, "stop_id": "TRANSFER_A", "transfers": [
                {"to_stop_index": 1, "to_stop_id": "TRANSFER_B", "distance_mm": 1_325_000}]},
            {"stop_index": 1, "stop_id": "TRANSFER_B", "transfers": [
                {"to_stop_index": 0, "to_stop_id": "TRANSFER_A", "distance_mm": 1_325_000},
                {"to_stop_index": 2, "to_stop_id": "TRANSFER_C", "distance_mm": 1_325_000}]},
            {"stop_index": 2, "stop_id": "TRANSFER_C", "transfers": [
                {"to_stop_index": 1, "to_stop_id": "TRANSFER_B", "distance_mm": 1_325_000}]},
        ]
        scoped = [{"stop_index": i, "stop_id": stop, "transfers": []}
                  for i, stop in enumerate(("TRANSFER_A", "TRANSFER_B", "TRANSFER_C"))]
        costs = {"access": [{"mode": "WALK", "stop_index": 0, "stop_id": "TRANSFER_A", "seconds": 12}],
                 "egress": [{"mode": "WALK", "stop_index": 2, "stop_id": "TRANSFER_C", "seconds": 12}]}
        samples = [{"departure_seconds": key,
                    "derived_civil_departure": (datetime(2026, 10, 14) + timedelta(seconds=key)).isoformat(),
                    "chains": [same_day_chain(key)] if identifier == "same_day_transfer" and key == 3600 else []}
                   for key in range(3600, 3960, 6)]
        cases.append({
            "id": identifier, "civil_departure": "2026-10-14T01:00:00", "network_timezone": "Australia/Melbourne",
            "request": deepcopy(REQUEST), "request_after": deepcopy(REQUEST),
            "stops": deepcopy(STOPS), "stops_after": deepcopy(STOPS),
            "services": deepcopy(SERVICES), "services_after": deepcopy(SERVICES),
            "schedules": deepcopy(schedules), "schedules_after": deepcopy(schedules),
            "active_services": list(active), "costs_before": deepcopy(costs), "costs_after": deepcopy(costs),
            "transfer_model": {"name": "fictional_same_stop_transfers_only", "applied": True,
                               "original": deepcopy(original), "after": deepcopy(original),
                               "scoped": deepcopy(scoped), "scoped_after": deepcopy(scoped), "restored": True},
            "samples": samples,
        })
    return {"cases": cases}


def rows(table):
    return list(csv.DictReader(StringIO(table.decode("utf-8"))))


def clock(seconds):
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


@pytest.mark.parametrize("identifier", IDS)
def test_isolated_fixture_preserves_raw_times_and_calendar_exceptions(identifier):
    tables = m.gtfs_tables(case_definition(identifier))
    expected_times, weekday, exception, _ = EXPECTED[identifier]
    expected_members = {"agency.txt", "stops.txt", "routes.txt", "trips.txt", "stop_times.txt",
                        "calendar.txt", "shapes.txt", "feed_info.txt"}
    if exception is not None:
        expected_members.add("calendar_dates.txt")
    assert set(tables) == expected_members
    assert all(b"\r" not in content and content.endswith(b"\n") for content in tables.values())
    assert rows(tables["agency.txt"])[0]["agency_timezone"] == "Australia/Melbourne"
    stops = rows(tables["stops.txt"])
    assert [(s["stop_id"], float(s["stop_lon"]), float(s["stop_lat"])) for s in stops] == [
        ("TRANSFER_A", 0.006, 0.018), ("TRANSFER_B", 0.018, 0.018), ("TRANSFER_C", 0.030, 0.018)]
    trips = rows(tables["trips.txt"])
    assert [(t["trip_id"], t["service_id"], t["route_id"]) for t in trips] == [
        ("TRANSFER_AB", "TRANSFER_FIRST", "TRANSFER_ROUTE_AB"),
        ("TRANSFER_BC", "TRANSFER_SECOND", "TRANSFER_ROUTE_BC")]
    times = rows(tables["stop_times.txt"])
    assert [t["arrival_time"] for t in times] == [clock(value) for value in expected_times]
    assert [t["departure_time"] for t in times] == [clock(value) for value in expected_times]
    assert [t["stop_id"] for t in times] == ["TRANSFER_A", "TRANSFER_B", "TRANSFER_B", "TRANSFER_C"]
    assert [t["stop_sequence"] for t in times] == ["1", "2", "1", "2"]
    assert [t["trip_id"] for t in times] == ["TRANSFER_AB", "TRANSFER_AB", "TRANSFER_BC", "TRANSFER_BC"]
    for item in times:
        assert (item["pickup_type"], item["drop_off_type"], item["timepoint"]) == ("0", "0", "1")
    calendars = rows(tables["calendar.txt"])
    weekdays = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    assert [k for k in weekdays if calendars[0][k] == "1"] == [weekday]
    assert [k for k in weekdays if calendars[1][k] == "1"] == ["wednesday"]
    assert all(c["start_date"] == "20261012" and c["end_date"] == "20261018" for c in calendars)
    if exception is None:
        assert "calendar_dates.txt" not in tables
    else:
        assert rows(tables["calendar_dates.txt"]) == [
            {"service_id": exception[0], "date": exception[1], "exception_type": "2"}]
    assert {r["route_type"] for r in rows(tables["routes.txt"])} == {"3"}
    shapes = rows(tables["shapes.txt"])
    assert [float(s["shape_pt_lon"]) for s in shapes] == [0.006, 0.012, 0.018, 0.018, 0.024, 0.030]
    assert {float(s["shape_pt_lat"]) for s in shapes} == {0.018}
    assert {t["shape_id"] for t in trips} == {s["shape_id"] for s in shapes}


def test_case_archives_are_reproducible_distinct_and_exclusive(tmp_path):
    digests = []
    for identifier in IDS:
        first, second = tmp_path / (identifier + ".zip"), tmp_path / (identifier + "-copy.zip")
        m.write_gtfs(first, case_definition(identifier))
        m.write_gtfs(second, case_definition(identifier))
        original = first.read_bytes()
        assert original == second.read_bytes()
        digests.append(hashlib.sha256(original).hexdigest())
        with ZipFile(first) as archive:
            expected_names = tuple(name for name in m.GTFS_FILENAMES
                                   if name != "calendar_dates.txt" or EXPECTED[identifier][2] is not None)
            assert tuple(archive.namelist()) == expected_names
            assert all(item.date_time == (2026, 1, 1, 0, 0, 0) and item.compress_type == ZIP_STORED
                       for item in archive.infolist())
        with pytest.raises(FileExistsError):
            m.write_gtfs(first, case_definition(identifier))
        assert first.read_bytes() == original
    assert len(set(digests)) == 8


@pytest.mark.parametrize("case", [None, {}, {"id": "unreviewed"},
    {"id": "same_day_transfer", "civil_departure": "2026-10-14T01:00:00", "expected_two_bus_path": 1},
    {"id": "same_day_transfer", "civil_departure": "2026-10-13T01:00:00", "expected_two_bus_path": True}])
def test_invalid_case_cannot_write_an_archive(tmp_path, case):
    output = tmp_path / "unexpected.zip"
    with pytest.raises(ValueError, match="Unknown or altered"):
        m.write_gtfs(output, case)
    assert not output.exists()


def test_sidecar_dates_are_independently_declared_and_preserve_removed_original_date():
    mixed = m.expected_service_instances(case_definition("mixed_day_transfer"))
    assert [(item["service_date"], item["original_departure_seconds"], item["expected_civil_departure"])
            for item in mixed] == [
        ("2026-10-13", 90300, "2026-10-14T01:05:00"), ("2026-10-14", 4500, "2026-10-14T01:15:00")]
    removed = m.expected_service_instances(case_definition("mixed_remove_first"))
    assert [item["active_on_original_service_date"] for item in removed] == [False, True]
    impossible = m.expected_service_instances(case_definition("same_day_impossible_connection"))
    assert impossible[1]["expected_civil_departure"] == "2026-10-14T01:09:00"
    assert impossible[0]["expected_civil_arrival"] == "2026-10-14T01:10:00"


def test_baseline_preserves_failure_and_does_not_rewrite_native_observations():
    report = valid_baseline_report()
    before = deepcopy(report["cases"])
    problems = m.validate_cases(report)
    assert problems == ["mixed_day_transfer: The required two-bus transfer itinerary is missing."]
    assert report["cases_passed"] == 7
    assert report["same_day_control_passed"] is True
    assert report["cases"] == before
    assert [row["native_samples_checked"] for row in report["case_diagnostics"]] == [60] * 8
    assert [row["native_paths_checked"] for row in report["case_diagnostics"]] == [0, 1, 0, 0, 0, 0, 0, 0]


def set_path(value, path, replacement):
    for key in path[:-1]:
        value = value[key]
    value[path[-1]] = replacement


def assert_case_rejected(report, index):
    problems = m.validate_cases(report)
    assert problems
    diagnostic = report["case_diagnostics"][index]
    assert diagnostic["status"] == "failed"
    assert diagnostic["problems"]
    return diagnostic


@pytest.mark.parametrize("path,value", [
    (("id",), "mixed_day_transfer"), (("civil_departure",), "2026-10-13T01:00:00"),
    (("network_timezone",), "UTC"), (("error",), "native failure"),
    (("request", "native_date"), "2026-10-13"), (("request", "from_time"), 90000),
    (("request", "to_time"), 4000), (("request", "max_rides"), 3),
    (("request", "max_rides"), 2.0), (("request", "walk_speed_mps"), float("nan")),
    (("request", "walk_speed_mps"), float("inf")), (("request", "from_lon"), 0.006),
    (("request", "monte_carlo_draws"), True), (("request", "reverse_search"), 0),
    (("request", "transit_modes"), ["BUS", "RAIL"]), (("request_after", "from_time"), 3601),
    (("active_services",), [0]), (("active_services",), [0, True]), (("active_services",), [1, 0]),
    (("active_services",), [0, 1, 1]), (("active_services",), [0, 1, 2]),
    (("stops", 1, "stop_index"), 0), (("stops", 0, "stop_index"), False),
    (("stops", 0, "stop_id"), "UNREVIEWED"), (("stops", 0, "scoped_stop_id"), "TRANSFER_A"),
    (("services", 1, "service_id"), "TRANSFER_FIRST"), (("services", 0, "service_code"), False),
    (("schedules", 0, "arrivals"), [90300, 90600]), (("schedules", 0, "departures"), [3901, 4200]),
    (("schedules", 0, "frequency_based"), 0), (("schedules", 0, "stop_indices"), [0, 2]),
    (("schedules", 0, "trip_id"), "TRANSFER_BC"), (("schedules", 0, "route_id"), "OTHER_ROUTE"),
    (("schedules", 1, "service_code"), 0), (("schedules", 1, "pattern_index"), 0),
    (("schedules_after", 1, "departures"), [4500, 4799]), (("services_after",), []),
    (("stops_after", 0, "stop_id"), "ALTERED"),
])
def test_request_and_catalog_evidence_cannot_be_silently_changed(path, value):
    report = valid_baseline_report()
    set_path(report["cases"][1], path, value)
    assert_case_rejected(report, 1)
    assert report["same_day_control_passed"] is False


def test_modulo_24_schedule_rewrite_is_rejected_even_when_both_snapshots_match():
    report = valid_baseline_report()
    case = report["cases"][0]
    for key in ("schedules", "schedules_after"):
        case[key][0].update(arrivals=[3900, 4200], departures=[3900, 4200])
    diagnostic = assert_case_rejected(report, 0)
    assert "raw timetable" in " ".join(diagnostic["problems"])


@pytest.mark.parametrize("path,value", [
    (("costs_before", "access", 0, "seconds"), 0),
    (("costs_before", "egress", 0, "seconds"), 12.0),
    (("costs_before", "access", 0, "stop_index"), False),
    (("costs_before", "access", 0, "stop_id"), "TRANSFER_B"),
    (("costs_before", "access", 0, "mode"), "CAR"), (("costs_before", "egress"), []),
    (("costs_after", "egress", 0, "seconds"), 11),
    (("transfer_model", "name"), "actual pedestrian paths"),
    (("transfer_model", "applied"), 1), (("transfer_model", "restored"), False),
    (("transfer_model", "original", 0, "transfers", 0, "distance_mm"), -1),
    (("transfer_model", "original", 0, "transfers", 0, "distance_mm"), True),
    (("transfer_model", "original", 0, "transfers", 0, "distance_mm"), 2_147_483_648),
    (("transfer_model", "original", 0, "transfers", 0, "to_stop_index"), 3),
    (("transfer_model", "original", 0, "transfers", 0, "to_stop_id"), "TRANSFER_C"),
    (("transfer_model", "original", 1, "stop_index"), 0),
    (("transfer_model", "scoped", 0, "transfers"), [{"to_stop_index": 1, "to_stop_id": "TRANSFER_B", "distance_mm": 1}]),
    (("transfer_model", "after", 0, "transfers", 0, "distance_mm"), 10),
    (("transfer_model", "scoped_after", 0, "transfers"), [{"to_stop_index": 1, "to_stop_id": "TRANSFER_B", "distance_mm": 1}]),
])
def test_artificial_costs_and_scoped_transfers_require_complete_unchanged_evidence(path, value):
    report = valid_baseline_report()
    set_path(report["cases"][1], path, value)
    assert_case_rejected(report, 1)


def test_an_extra_endpoint_cost_cannot_hide_a_one_bus_shortcut():
    report = valid_baseline_report()
    case = report["cases"][1]
    case["costs_before"]["access"].append({"mode": "WALK", "stop_index": 1, "stop_id": "TRANSFER_B", "seconds": 12})
    case["costs_after"] = deepcopy(case["costs_before"])
    assert_case_rejected(report, 1)


@pytest.mark.parametrize("field,value", [("departure_seconds", True), ("departure_seconds", 3599),
    ("departure_seconds", 3960), ("departure_seconds", 3600.0),
    ("derived_civil_departure", "2026-10-13T25:00:00"), ("chains", {}), ("chains", [None])])
def test_malformed_native_samples_are_not_ignored_for_negative_controls(field, value):
    report = valid_baseline_report()
    report["cases"][2]["samples"][0][field] = value
    assert_case_rejected(report, 2)


@pytest.mark.parametrize("change", ["missing", "duplicate", "unordered", "extra", "unbounded_paths"])
def test_sample_inventory_is_complete_bounded_and_ordered(change):
    report = valid_baseline_report()
    samples = report["cases"][2]["samples"]
    if change == "missing":
        samples.pop()
    elif change == "duplicate":
        samples[1] = deepcopy(samples[0])
    elif change == "unordered":
        samples[0], samples[1] = samples[1], samples[0]
    elif change == "extra":
        samples.append(deepcopy(samples[-1]))
    else:
        samples[0]["chains"] = [same_day_chain()] * 11
    assert_case_rejected(report, 2)


@pytest.mark.parametrize("state,field,value", [
    (0, "time", 3611), (0, "stop", 1), (0, "round", 1), (0, "pattern", 0),
    (1, "time", 4199), (1, "board_time", 3899), (1, "round", 2), (1, "stop", 2),
    (1, "trip", 1), (1, "pattern", 1), (1, "board_stop_position", 1),
    (1, "alight_stop_position", 0), (1, "time", 4200.0), (1, "round", True),
    (2, "pattern", 0), (2, "round", 1), (2, "stop", 1), (2, "board_time", 4140),
    (3, "time", 4813), (3, "round", 3), (3, "stop", 2), (3, "pattern", 1),
    (0, "access_mode", "BICYCLE"), (1, "egress_mode", "WALK"), (3, "egress_mode", None),
])
def test_native_chain_validates_each_state_timetable_order_mode_and_egress_round(state, field, value):
    report = valid_baseline_report()
    report["cases"][1]["samples"][0]["chains"][0][state][field] = value
    assert_case_rejected(report, 1)


def test_boarding_requires_strictly_more_than_sixty_seconds_after_access():
    report = valid_baseline_report()
    sample = report["cases"][1]["samples"][38]  # 3828 + 12 + 60 == first departure 3900.
    assert sample["departure_seconds"] == 3828
    sample["chains"] = [same_day_chain(3828)]
    diagnostic = assert_case_rejected(report, 1)
    assert "slack" in " ".join(diagnostic["problems"])


@pytest.mark.parametrize("case_index", range(2, 8))
def test_negative_controls_reject_any_returned_path_instead_of_counting_only_expected_matches(case_index):
    report = valid_baseline_report()
    report["cases"][case_index]["samples"][0]["chains"] = [same_day_chain()]
    assert_case_rejected(report, case_index)


@pytest.mark.parametrize("chain", [[], None, {}, [None], [{"time": 3612}] * 4])
def test_incomplete_chain_cannot_be_discarded_as_an_empty_negative_result(chain):
    report = valid_baseline_report()
    report["cases"][7]["samples"][0]["chains"] = [chain]
    assert_case_rejected(report, 7)


def test_missing_same_day_positive_stops_date_selection_attribution():
    report = valid_baseline_report()
    report["cases"][1]["samples"][0]["chains"] = []
    problems = m.validate_cases(report)
    assert report["cases_passed"] == 6
    assert report["same_day_control_passed"] is False
    assert any("do not attribute" in problem for problem in problems)


@pytest.mark.parametrize("change", ["missing", "extra", "swapped", "not_list"])
def test_case_inventory_is_exact_and_ordered(change):
    report = valid_baseline_report()
    if change == "missing":
        report["cases"].pop()
    elif change == "extra":
        report["cases"].append(deepcopy(report["cases"][-1]))
    elif change == "swapped":
        report["cases"][2], report["cases"][3] = report["cases"][3], report["cases"][2]
    else:
        report["cases"] = {}
    problems = m.validate_cases(report)
    assert len(problems) > 1
    assert len(report["case_diagnostics"]) == 8
    assert len(problems) <= 12
