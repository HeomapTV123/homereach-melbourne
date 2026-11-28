"""Fictional three-stop timetables and an independent native transfer oracle.

This is a transit-only compatibility diagnostic. Access and egress are fixed
artificial costs, street transfers are temporarily disabled, and no street or
station access is validated. It preserves the failing mixed-service-day case;
it does not implement a correction or normalize an engine-returned itinerary.
The fixed service dates do not cross a daylight-saving transition.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo


FIXTURE_ID = "homereach_service_day_transfer_v1"
TIMEZONE = "Australia/Melbourne"
ORIGIN = (0.0061, 0.018)
DESTINATION = (0.0299, 0.018)
QUERY_WINDOW_SECONDS = 360
MAX_SAMPLES = 60
MAX_PROBLEM_EXAMPLES = 12
BOARD_SLACK_SECONDS = 60
STOP_IDS = ("TRANSFER_A", "TRANSFER_B", "TRANSFER_C")
GTFS_FILENAMES = (
    "agency.txt", "stops.txt", "routes.txt", "trips.txt", "stop_times.txt",
    "calendar.txt", "calendar_dates.txt", "shapes.txt", "feed_info.txt",
)
ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)
CASES = (
    {"id": "mixed_day_transfer", "civil_departure": "2026-10-14T01:00:00", "expected_two_bus_path": True},
    {"id": "same_day_transfer", "civil_departure": "2026-10-14T01:00:00", "expected_two_bus_path": True},
    {"id": "mixed_remove_first", "civil_departure": "2026-10-14T01:00:00", "expected_two_bus_path": False},
    {"id": "mixed_remove_second", "civil_departure": "2026-10-14T01:00:00", "expected_two_bus_path": False},
    {"id": "mixed_impossible_connection", "civil_departure": "2026-10-14T01:00:00", "expected_two_bus_path": False},
    {"id": "same_day_remove_first", "civil_departure": "2026-10-14T01:00:00", "expected_two_bus_path": False},
    {"id": "same_day_remove_second", "civil_departure": "2026-10-14T01:00:00", "expected_two_bus_path": False},
    {"id": "same_day_impossible_connection", "civil_departure": "2026-10-14T01:00:00", "expected_two_bus_path": False},
)

# Fixture-generation inputs are raw GTFS strings. The oracle below declares
# integer times and calendar expectations separately, not from these tables.
# (first departure/arrival, first weekday, second departure/arrival, exception).
_TABLE_CASES = {
    "mixed_day_transfer": ("25:05:00", "25:10:00", "tuesday", "01:15:00", "01:20:00", None),
    "same_day_transfer": ("01:05:00", "01:10:00", "wednesday", "01:15:00", "01:20:00", None),
    "mixed_remove_first": ("25:05:00", "25:10:00", "tuesday", "01:15:00", "01:20:00", ("TRANSFER_FIRST", "20261013", "2")),
    "mixed_remove_second": ("25:05:00", "25:10:00", "tuesday", "01:15:00", "01:20:00", ("TRANSFER_SECOND", "20261014", "2")),
    "mixed_impossible_connection": ("25:05:00", "25:10:00", "tuesday", "01:09:00", "01:14:00", None),
    "same_day_remove_first": ("01:05:00", "01:10:00", "wednesday", "01:15:00", "01:20:00", ("TRANSFER_FIRST", "20261014", "2")),
    "same_day_remove_second": ("01:05:00", "01:10:00", "wednesday", "01:15:00", "01:20:00", ("TRANSFER_SECOND", "20261014", "2")),
    "same_day_impossible_connection": ("01:05:00", "01:10:00", "wednesday", "01:09:00", "01:14:00", None),
}

# Independent calendar/timetable oracle: first raw times and original service
# date, second raw times, active current-date service IDs, removed service ID.
_ORACLE = {
    "mixed_day_transfer": (90300, 90600, "2026-10-13", 4500, 4800, {"TRANSFER_SECOND"}, None),
    "same_day_transfer": (3900, 4200, "2026-10-14", 4500, 4800, {"TRANSFER_FIRST", "TRANSFER_SECOND"}, None),
    "mixed_remove_first": (90300, 90600, "2026-10-13", 4500, 4800, {"TRANSFER_SECOND"}, "TRANSFER_FIRST"),
    "mixed_remove_second": (90300, 90600, "2026-10-13", 4500, 4800, set(), "TRANSFER_SECOND"),
    "mixed_impossible_connection": (90300, 90600, "2026-10-13", 4140, 4440, {"TRANSFER_SECOND"}, None),
    "same_day_remove_first": (3900, 4200, "2026-10-14", 4500, 4800, {"TRANSFER_SECOND"}, "TRANSFER_FIRST"),
    "same_day_remove_second": (3900, 4200, "2026-10-14", 4500, 4800, {"TRANSFER_FIRST"}, "TRANSFER_SECOND"),
    "same_day_impossible_connection": (3900, 4200, "2026-10-14", 4140, 4440, {"TRANSFER_FIRST", "TRANSFER_SECOND"}, None),
}
REQUEST_ORACLE = {
    "native_date": "2026-10-14", "from_time": 3600, "to_time": 3960,
    "from_lon": 0.0061, "from_lat": 0.018, "to_lon": 0.0299, "to_lat": 0.018,
    "monte_carlo_draws": 60, "max_trip_duration_minutes": 30, "max_rides": 2,
    "suboptimal_minutes": 5, "walk_speed_mps": 1.0, "reverse_search": False,
    "transit_modes": ["BUS"], "access_modes": ["WALK"], "egress_modes": ["WALK"],
}
STATE_INTS = ("time", "board_time", "pattern", "trip", "round", "stop",
              "board_stop_position", "alight_stop_position")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _strict_equal(actual, expected):
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(actual) == set(expected) and all(_strict_equal(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(_strict_equal(a, b) for a, b in zip(actual, expected))
    return actual == expected


def _case(case):
    _require(any(_strict_equal(case, fixed) for fixed in CASES), "Unknown or altered transfer fixture case.")
    return case["id"]


def _csv(header, rows):
    stream = StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def gtfs_tables(case: dict) -> dict[str, bytes]:
    """Generate one isolated deterministic three-stop, two-trip timetable."""
    identifier = _case(case)
    depart_a, arrive_b, weekday, depart_b, arrive_c, exception = _TABLE_CASES[identifier]
    trips = [
        ("TRANSFER_ROUTE_AB", "TRANSFER_FIRST", "TRANSFER_AB", "TRANSFER_SHAPE_AB"),
        ("TRANSFER_ROUTE_BC", "TRANSFER_SECOND", "TRANSFER_BC", "TRANSFER_SHAPE_BC"),
    ]
    times = [
        ("TRANSFER_AB", depart_a, depart_a, "TRANSFER_A", "1", "0", "0", "1"),
        ("TRANSFER_AB", arrive_b, arrive_b, "TRANSFER_B", "2", "0", "0", "1"),
        ("TRANSFER_BC", depart_b, depart_b, "TRANSFER_B", "1", "0", "0", "1"),
        ("TRANSFER_BC", arrive_c, arrive_c, "TRANSFER_C", "2", "0", "0", "1"),
    ]
    tables = {
        "agency.txt": _csv(
            ("agency_id", "agency_name", "agency_url", "agency_timezone", "agency_lang"),
            [("TRANSFER", "HomeReach Fictional Transfer", "https://example.invalid/homereach-transfer", TIMEZONE, "en")]),
        "stops.txt": _csv(
            ("stop_id", "stop_name", "stop_lat", "stop_lon", "location_type"),
            [("TRANSFER_A", "Fictional A", "0.0180000", "0.0060000", "0"),
             ("TRANSFER_B", "Fictional B", "0.0180000", "0.0180000", "0"),
             ("TRANSFER_C", "Fictional C", "0.0180000", "0.0300000", "0")]),
        "routes.txt": _csv(
            ("route_id", "agency_id", "route_short_name", "route_long_name", "route_type"),
            [(route, "TRANSFER", route, "Fictional two-ride transfer", "3") for route, *_ in trips]),
        "trips.txt": _csv(
            ("route_id", "service_id", "trip_id", "trip_headsign", "direction_id", "shape_id"),
            [(route, service, trip, "Fictional East", "0", shape) for route, service, trip, shape in trips]),
        "stop_times.txt": _csv(
            ("trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence", "pickup_type", "drop_off_type", "timepoint"), times),
        "calendar.txt": _csv(
            ("service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "start_date", "end_date"),
            [("TRANSFER_FIRST", "0", "1" if weekday == "tuesday" else "0", "1" if weekday == "wednesday" else "0", "0", "0", "0", "0", "20261012", "20261018"),
             ("TRANSFER_SECOND", "0", "0", "1", "0", "0", "0", "0", "20261012", "20261018")]),
        "calendar_dates.txt": _csv(("service_id", "date", "exception_type"), [exception] if exception else []),
        "shapes.txt": _csv(
            ("shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"),
            [("TRANSFER_SHAPE_AB", "0.0180000", lon, str(i)) for i, lon in enumerate(("0.0060000", "0.0120000", "0.0180000"), 1)]
            + [("TRANSFER_SHAPE_BC", "0.0180000", lon, str(i)) for i, lon in enumerate(("0.0180000", "0.0240000", "0.0300000"), 1)]),
        "feed_info.txt": _csv(
            ("feed_publisher_name", "feed_publisher_url", "feed_lang", "feed_start_date", "feed_end_date", "feed_version"),
            [("HomeReach fictional transfer fixture", "https://example.invalid/homereach-transfer", "en", "20261012", "20261018", FIXTURE_ID + "-" + identifier)]),
    }
    # R5 rejects a present calendar_dates.txt with no data rows. The GTFS table
    # is optional when calendar.txt supplies every service without exceptions.
    if exception is None:
        del tables["calendar_dates.txt"]
    return tables


def write_gtfs(path: Path, case: dict) -> None:
    """Write an exclusive, reproducible per-case ZIP without replacing a file."""
    tables = gtfs_tables(case)
    with ZipFile(path, mode="x", compression=ZIP_STORED) as archive:
        for name in GTFS_FILENAMES:
            if name not in tables:
                continue
            info = ZipInfo(name, date_time=ZIP_TIMESTAMP)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = ZIP_STORED
            archive.writestr(info, tables[name])


def expected_service_instances(case: dict) -> list[dict]:
    """Independent sidecar expectations; these are not native engine fields."""
    first, first_end, first_date, second, second_end, _, removed = _ORACLE[_case(case)]
    impossible = second == 4140
    return [
        {"trip_id": "TRANSFER_AB", "service_id": "TRANSFER_FIRST", "service_date": first_date,
         "original_departure_seconds": first, "original_arrival_seconds": first_end,
         "expected_civil_departure": "2026-10-14T01:05:00", "expected_civil_arrival": "2026-10-14T01:10:00",
         "active_on_original_service_date": removed != "TRANSFER_FIRST"},
        {"trip_id": "TRANSFER_BC", "service_id": "TRANSFER_SECOND", "service_date": "2026-10-14",
         "original_departure_seconds": second, "original_arrival_seconds": second_end,
         "expected_civil_departure": "2026-10-14T01:09:00" if impossible else "2026-10-14T01:15:00",
         "expected_civil_arrival": "2026-10-14T01:14:00" if impossible else "2026-10-14T01:20:00",
         "active_on_original_service_date": removed != "TRANSFER_SECOND"},
    ]


def _catalog(observed, case):
    services, stops, schedules = (observed.get(k) for k in ("services", "stops", "schedules"))
    _require(isinstance(services, list) and len(services) == 2, "Expected two native services.")
    _require(isinstance(stops, list) and len(stops) == 3, "Expected three native stops.")
    _require(isinstance(schedules, list) and len(schedules) == 2, "Expected two native schedules.")
    service_map, stop_map = {}, {}
    for row in services:
        _require(isinstance(row, dict) and type(row.get("service_code")) is int and row["service_code"] >= 0
                 and isinstance(row.get("service_id"), str) and row["service_code"] not in service_map,
                 "Malformed or duplicate native service catalog entry.")
        service_map[row["service_code"]] = row["service_id"]
    _require(set(service_map.values()) == {"TRANSFER_FIRST", "TRANSFER_SECOND"}, "Native service identity differs from the oracle.")
    for row in stops:
        _require(isinstance(row, dict) and type(row.get("stop_index")) is int and row["stop_index"] >= 0
                 and isinstance(row.get("stop_id"), str) and isinstance(row.get("scoped_stop_id"), str)
                 and row["scoped_stop_id"].rpartition(":")[0]
                 and row["scoped_stop_id"].split(":")[-1] == row["stop_id"] and row["stop_index"] not in stop_map,
                 "Malformed or duplicate native stop catalog entry.")
        stop_map[row["stop_index"]] = row["stop_id"]
    _require(set(stop_map.values()) == set(STOP_IDS), "Native stop identity differs from the oracle.")
    _require(sorted(stop_map) == list(range(3)) and sorted(service_map) == list(range(2)), "Native catalog indexes are not complete.")
    schedule_map = _schedules(schedules, case, service_map, stop_map)
    for name in ("services", "stops", "schedules"):
        _require(_strict_equal(observed.get(name + "_after"), observed.get(name)), "Native " + name + " catalog changed.")
    return service_map, stop_map, schedule_map


def _schedules(rows, case, services, stops):
    first, first_end, _, second, second_end, _, _ = _ORACLE[case["id"]]
    expected = {
        "TRANSFER_AB": ("TRANSFER_ROUTE_AB", "TRANSFER_FIRST", [first, first_end], ["TRANSFER_A", "TRANSFER_B"]),
        "TRANSFER_BC": ("TRANSFER_ROUTE_BC", "TRANSFER_SECOND", [second, second_end], ["TRANSFER_B", "TRANSFER_C"]),
    }
    result, seen = {}, set()
    for row in rows:
        _require(isinstance(row, dict) and all(type(row.get(k)) is int and row[k] >= 0 for k in
                 ("pattern_index", "trip_index", "service_code")), "Malformed native schedule index.")
        trip = row.get("trip_id")
        _require(isinstance(trip, str) and trip in expected and trip not in seen, "Unexpected or duplicate native trip.")
        key = (row["pattern_index"], row["trip_index"])
        _require(key not in result, "Duplicate native pattern/trip index.")
        route, service, times, names = expected[trip]
        _require(row.get("route_id") == route and services.get(row["service_code"]) == service
                 and row.get("frequency_based") is False and isinstance(row.get("scoped_trip_id"), str)
                 and row["scoped_trip_id"].rpartition(":")[0] and row["scoped_trip_id"].split(":")[-1] == trip
                 and _strict_equal(row.get("arrivals"), times) and _strict_equal(row.get("departures"), times)
                 and _strict_equal(row.get("stop_ids"), names), "Native schedule differs from the independent raw timetable.")
        indexes = row.get("stop_indices")
        _require(isinstance(indexes, list) and len(indexes) == 2 and all(type(i) is int for i in indexes)
                 and [stops.get(i) for i in indexes] == names, "Native schedule stop indexes disagree with the catalog.")
        seen.add(trip)
        result[key] = row
    _require(seen == set(expected), "Incomplete native trip catalog.")
    return result


def _costs(value, stop_map):
    _require(isinstance(value, dict) and set(value) == {"access", "egress"}, "Missing artificial access/egress maps.")
    for role, stop in (("access", "TRANSFER_A"), ("egress", "TRANSFER_C")):
        rows = value[role]
        _require(isinstance(rows, list) and len(rows) == 1, "Artificial " + role + " must contain only its endpoint stop.")
        row = rows[0]
        _require(isinstance(row, dict) and row.get("mode") == "WALK" and type(row.get("stop_index")) is int
                 and stop_map.get(row["stop_index"]) == stop and row.get("stop_id") == stop
                 and type(row.get("seconds")) is int and row["seconds"] == 12,
                 "Artificial " + role + " cost must be exactly twelve seconds at the fixed endpoint.")


def _transfer_rows(rows, stop_map):
    _require(isinstance(rows, list) and len(rows) == 3, "Street-transfer inventory must include all three stops.")
    seen = []
    for row in rows:
        _require(isinstance(row, dict) and type(row.get("stop_index")) is int
                 and row["stop_index"] in stop_map and row.get("stop_id") == stop_map[row["stop_index"]]
                 and isinstance(row.get("transfers"), list) and len(row["transfers"]) <= 3,
                 "Malformed street-transfer inventory row.")
        seen.append(row["stop_index"])
        targets = set()
        for transfer in row["transfers"]:
            _require(isinstance(transfer, dict) and type(transfer.get("to_stop_index")) is int
                     and transfer["to_stop_index"] in stop_map and transfer["to_stop_index"] not in targets
                     and transfer.get("to_stop_id") == stop_map[transfer["to_stop_index"]]
                     and type(transfer.get("distance_mm")) is int and 0 <= transfer["distance_mm"] <= 2_147_483_647,
                     "Malformed or duplicate street-transfer target.")
            targets.add(transfer["to_stop_index"])
    _require(seen == sorted(stop_map), "Street-transfer inventory has missing, duplicate or reordered stops.")


def _transfers(model, stop_map):
    _require(isinstance(model, dict) and set(model) == {"name", "applied", "original", "scoped", "scoped_after", "restored", "after"},
             "Missing scoped street-transfer evidence.")
    _require(model["name"] == "fictional_same_stop_transfers_only" and model["applied"] is True,
             "The explicit same-stop transfer model was not applied.")
    for name in ("original", "scoped", "scoped_after", "after"):
        _transfer_rows(model[name], stop_map)
    _require(all(not row["transfers"] for row in model["scoped"]), "Street transfers were not disabled for the transit-only experiment.")
    _require(_strict_equal(model["scoped"], model["scoped_after"]), "Scoped street transfers changed during routing.")
    _require(model["restored"] is True and _strict_equal(model["original"], model["after"]), "Original street transfers were not restored.")


def _check_chain(chain, sample, case, stops, schedules, active):
    _require(isinstance(chain, list) and len(chain) == 4, "Expected a complete native access/BUS/BUS/egress chain.")
    _require(all(isinstance(s, dict) and all(type(s.get(k)) is int for k in STATE_INTS) for s in chain),
             "Malformed native state fields.")
    access, first, second, egress = chain
    _require(stops.get(access["stop"]) == "TRANSFER_A" and access["pattern"] == -1 and access["trip"] == -1
             and access["round"] == 0 and access["time"] == sample + 12
             and egress["stop"] == -1 and egress["pattern"] == -1 and egress["trip"] == -1 and egress["round"] == 0
             and all(s.get("access_mode") == "WALK" for s in chain) and egress.get("egress_mode") == "WALK"
             and all(s.get("egress_mode") is None for s in chain[:-1]), "Unexpected access/egress state or walking mode.")
    previous = access
    civil = expected_service_instances(case)
    for ride, trip, stop, number, expected in ((first, "TRANSFER_AB", "TRANSFER_B", 1, civil[0]),
                                               (second, "TRANSFER_BC", "TRANSFER_C", 2, civil[1])):
        schedule = schedules.get((ride["pattern"], ride["trip"]))
        _require(schedule is not None and schedule["trip_id"] == trip and schedule["service_code"] in active,
                 "Native chain uses an unexpected trip or inactive current-date service.")
        _require(stops.get(ride["stop"]) == stop and ride["round"] == number
                 and ride["board_stop_position"] == 0 and ride["alight_stop_position"] == 1,
                 "Native BUS order, round or stop positions differ from the required chain.")
        _require(ride["board_time"] == schedule["departures"][0] and ride["time"] == schedule["arrivals"][1]
                 and ride["board_time"] > previous["time"] + BOARD_SLACK_SECONDS,
                 "Native ride timing violates the raw timetable or strict boarding/transfer slack.")
        for value, field in ((ride["board_time"], "expected_civil_departure"), (ride["time"], "expected_civil_arrival")):
            derived = (datetime(2026, 10, 14) + timedelta(seconds=value)).isoformat()
            _require(derived == expected[field], "Derived native civil time differs from the independent oracle.")
        previous = ride
    _require(egress["time"] == second["time"] + 12 and 0 < egress["time"] - sample <= 1800,
             "Native egress or total duration differs from the fixed cost/limit.")
    _require(case["expected_two_bus_path"], "A negative transfer control returned the forbidden two-bus chain.")


def _check_case(observed, case):
    _require(isinstance(observed, dict) and observed.get("id") == case["id"]
             and observed.get("civil_departure") == case["civil_departure"], "Missing, reordered or altered transfer case.")
    _require(not observed.get("error"), "Native query error: " + str(observed.get("error")))
    _require(observed.get("network_timezone") == TIMEZONE, "Native network timezone differs from the fixture.")
    request = observed.get("request")
    _require(_strict_equal(request, REQUEST_ORACLE), "Native request differs from the fixed current-date baseline.")
    _require(_strict_equal(observed.get("request_after"), request), "Native request mutated during routing.")
    services, stops, schedules = _catalog(observed, case)
    _costs(observed.get("costs_before"), stops)
    _require(_strict_equal(observed.get("costs_before"), observed.get("costs_after")), "Artificial walking costs changed.")
    _transfers(observed.get("transfer_model"), stops)
    active = observed.get("active_services")
    _require(isinstance(active, list) and all(type(i) is int and i in services for i in active)
             and active == sorted(set(active)) and {services[i] for i in active} == _ORACLE[case["id"]][5],
             "Native active services differ from the independent current-date calendar oracle.")
    samples = observed.get("samples")
    _require(isinstance(samples, list) and len(samples) == MAX_SAMPLES, "Native sample inventory is missing or incomplete.")
    keys, paths = [], 0
    for row in samples:
        _require(isinstance(row, dict) and type(row.get("departure_seconds")) is int
                 and 3600 <= row["departure_seconds"] < 3960, "Malformed or out-of-window native sample key.")
        key = row["departure_seconds"]
        expected_civil = (datetime(2026, 10, 14) + timedelta(seconds=key)).isoformat()
        _require(row.get("derived_civil_departure") == expected_civil, "Derived native sample date is incorrect.")
        chains = row.get("chains")
        _require(isinstance(chains, list) and len(chains) <= 10, "Malformed or unbounded native sample path list.")
        for chain in chains:
            _check_chain(chain, key, case, stops, schedules, active)
        keys.append(key)
        paths += len(chains)
    _require(keys == sorted(set(keys)), "Native sample keys are duplicated or unordered.")
    return len(samples), paths


def validate_cases(report: dict) -> list[str]:
    """Validate all returned native observations; preserve the mixed-day failure."""
    observations = report.get("cases")
    problems, diagnostics = [], []
    if not isinstance(observations, list) or len(observations) != len(CASES):
        problems.append("Missing or extra native transfer cases.")
    if not isinstance(observations, list):
        observations = []
    for index, case in enumerate(CASES):
        check = {"id": case["id"], "expected_two_bus_path": case["expected_two_bus_path"],
                 "independent_expected_service_instances": expected_service_instances(case),
                 "native_samples_checked": 0, "native_paths_checked": 0, "problems": []}
        try:
            observed = observations[index] if index < len(observations) else None
            samples, paths = _check_case(observed, case)
            check.update(native_samples_checked=samples, native_paths_checked=paths)
            _require(not case["expected_two_bus_path"] or paths > 0, "The required two-bus transfer itinerary is missing.")
        except (KeyError, ValueError, TypeError, OverflowError) as error:
            check["problems"].append(str(error)[:500])
        check.update(status="failed" if check["problems"] else "passed", problem_count=len(check["problems"]))
        diagnostics.append(check)
        problems.extend(case["id"] + ": " + message for message in check["problems"])
    report["case_diagnostics"] = diagnostics
    report["cases_passed"] = sum(c["status"] == "passed" for c in diagnostics)
    report["same_day_control_passed"] = diagnostics[1]["status"] == "passed"
    if not report["same_day_control_passed"]:
        problems.append("Same-day transfer control failed; do not attribute mixed-day failure to date selection alone.")
    return problems[:MAX_PROBLEM_EXAMPLES]
