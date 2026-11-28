"""Independent oracle for a fixed native service-date anchor experiment.

This diagnostic compares representations of the same civil interval. It never
rewrites engine states into itineraries and is not a general service-day repair.
The fixed dates do not cross a daylight-saving transition.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import routing_service_day_fixture as fixture


ARMS = ("current_date", "previous_date")
WINDOW_SECONDS = 360
MAX_SAMPLES = 60
MAX_PROBLEM_EXAMPLES = 16

# Explicit oracle values: independent of the GTFS generator and native imports.
PAIRS = (
    {"id": "previous_service_24h", "civil_departure": "2026-10-14T00:10:00",
     "current_trip_id": None, "previous_trip_id": "SD_TRIP_24"},
    {"id": "previous_service_25h", "civil_departure": "2026-10-14T01:00:00",
     "current_trip_id": None, "previous_trip_id": "SD_TRIP_25"},
    {"id": "previous_service_32h", "civil_departure": "2026-10-14T08:37:00",
     "current_trip_id": None, "previous_trip_id": "SD_TRIP_32"},
    {"id": "calendar_addition", "civil_departure": "2026-10-14T02:00:00",
     "current_trip_id": None, "previous_trip_id": "SD_TRIP_ADDED"},
    {"id": "next_date_daytime_control", "civil_departure": "2026-10-14T09:00:00",
     "current_trip_id": "SD_TRIP_WEDNESDAY", "previous_trip_id": None},
    {"id": "calendar_removal", "civil_departure": "2026-10-14T03:00:00",
     "current_trip_id": None, "previous_trip_id": None},
    {"id": "inactive_date", "civil_departure": "2026-10-15T01:00:00",
     "current_trip_id": None, "previous_trip_id": None},
)

# trip_id: (route_id, service_id, first-stop seconds, last-stop seconds).
SCHEDULE_ORACLE = {
    "SD_TRIP_DAY": ("SD_DAY", "SD_TUESDAY", 29100, 29400),
    "SD_TRIP_WEDNESDAY": ("SD_WEDNESDAY", "SD_WEDNESDAY", 32700, 33000),
    "SD_TRIP_ADDED_DAY": ("SD_ADDED_DAY", "SD_ADDED", 36300, 36600),
    "SD_TRIP_REMOVED_DAY": ("SD_REMOVED_DAY", "SD_REMOVED", 39900, 40200),
    "SD_TRIP_CROSS": ("SD_CROSS_MIDNIGHT", "SD_TUESDAY", 86280, 86580),
    "SD_TRIP_24": ("SD_AFTER_24", "SD_TUESDAY", 87300, 87600),
    "SD_TRIP_25": ("SD_AFTER_25", "SD_TUESDAY", 90300, 90600),
    "SD_TRIP_32": ("SD_AFTER_32", "SD_TUESDAY", 117720, 118020),
    "SD_TRIP_ADDED": ("SD_ADDED", "SD_ADDED", 93900, 94200),
    "SD_TRIP_REMOVED": ("SD_REMOVED", "SD_REMOVED", 97500, 97800),
}
ACTIVE_SERVICES = {
    "2026-10-13": {"SD_TUESDAY", "SD_ADDED"},
    "2026-10-14": {"SD_WEDNESDAY"},
    "2026-10-15": set(),
}
STATE_INTS = ("time", "board_time", "pattern", "trip", "round", "stop",
              "board_stop_position", "alight_stop_position")
COMMON_REQUEST = {
    "from_lon": 0.0061, "from_lat": 0.018,
    "to_lon": 0.0299, "to_lat": 0.018,
    "monte_carlo_draws": 60, "max_trip_duration_minutes": 20, "max_rides": 1,
    "walk_speed_mps": 1.0, "transit_modes": ["BUS"],
    "access_modes": ["WALK"], "egress_modes": ["WALK"], "reverse_search": False,
}


def request_spec(pair: dict, arm: str) -> dict:
    """Define the three native fields changed between two fixed request clones."""
    if pair not in PAIRS or arm not in ARMS:
        raise ValueError("Unknown or altered service-date anchor case.")
    civil = datetime.fromisoformat(pair["civil_departure"])
    anchor = civil.date() - timedelta(days=arm == "previous_date")
    start = int((civil - datetime.combine(anchor, datetime.min.time())).total_seconds())
    return {"native_date": anchor.isoformat(), "from_time": start,
            "to_time": start + WINDOW_SECONDS}


def civil_time(native_date: str, seconds: int) -> str:
    """Diagnostic derivation; never presented as an engine-returned datetime."""
    if type(seconds) is not int or not 0 <= seconds <= 3 * 86400:
        raise ValueError("Invalid native service-day seconds.")
    if not isinstance(native_date, str) or date.fromisoformat(native_date).isoformat() != native_date:
        raise ValueError("Invalid native service date.")
    return (datetime.combine(date.fromisoformat(native_date), datetime.min.time())
            + timedelta(seconds=seconds)).isoformat()


class _Problems:
    def __init__(self):
        self.count = 0
        self.examples = []

    def add(self, message):
        self.count += 1
        if len(self.examples) < MAX_PROBLEM_EXAMPLES:
            self.examples.append(str(message)[:500])


def _strict_equal(actual, expected):
    """Reject bool-as-int and other JSON type substitutions recursively."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(actual) == set(expected) and all(_strict_equal(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(_strict_equal(a, e) for a, e in zip(actual, expected))
    return actual == expected


def _catalog(report, problems):
    services, stops, schedules = (report.get(k) for k in ("services", "stops", "schedules"))
    if not isinstance(services, list) or not isinstance(stops, list) or not isinstance(schedules, list):
        raise ValueError("Missing native service, stop or schedule catalog.")
    service_map, stop_map, schedule_map = {}, {}, {}
    for row in services:
        if (not isinstance(row, dict) or type(row.get("service_code")) is not int
                or row["service_code"] < 0 or not isinstance(row.get("service_id"), str)
                or row["service_code"] in service_map):
            raise ValueError("Malformed or duplicate native service catalog entry.")
        service_map[row["service_code"]] = row["service_id"]
    if len(service_map) != 4 or set(service_map.values()) != {"SD_TUESDAY", "SD_WEDNESDAY", "SD_ADDED", "SD_REMOVED"}:
        raise ValueError("Native service catalog differs from the independent fixture oracle.")
    for row in stops:
        if (not isinstance(row, dict) or type(row.get("stop_index")) is not int
                or row["stop_index"] < 0 or not isinstance(row.get("stop_id"), str)
                or not isinstance(row.get("scoped_stop_id"), str)
                or row["scoped_stop_id"].split(":")[-1] != row["stop_id"]
                or row["stop_index"] in stop_map):
            raise ValueError("Malformed or duplicate native stop catalog entry.")
        stop_map[row["stop_index"]] = row["stop_id"]
    if len(stop_map) != 2 or set(stop_map.values()) != {fixture.START_STOP_ID, fixture.END_STOP_ID}:
        raise ValueError("Native stop catalog differs from the fixture.")
    trip_ids = set()
    for row in schedules:
        if (not isinstance(row, dict) or any(type(row.get(k)) is not int or row[k] < 0
                for k in ("pattern_index", "trip_index", "service_code"))):
            raise ValueError("Malformed native schedule identity.")
        key = (row["pattern_index"], row["trip_index"])
        trip = row.get("trip_id")
        if key in schedule_map or trip in trip_ids or trip not in SCHEDULE_ORACLE:
            raise ValueError("Duplicate or unexpected native schedule.")
        route, service, departure, arrival = SCHEDULE_ORACLE[trip]
        if (row.get("route_id") != route or service_map.get(row["service_code"]) != service
                or row.get("frequency_based") is not False
                or not _strict_equal(row.get("arrivals"), [departure, arrival])
                or not _strict_equal(row.get("departures"), [departure, arrival])
                or not _strict_equal(row.get("stop_ids"), [fixture.START_STOP_ID, fixture.END_STOP_ID])
                or not isinstance(row.get("scoped_trip_id"), str)
                or row["scoped_trip_id"].split(":")[-1] != trip):
            raise ValueError("Native schedule differs from the independent timetable oracle.")
        indices = row.get("stop_indices")
        if (not isinstance(indices, list) or len(indices) != 2
                or any(type(i) is not int for i in indices)
                or [stop_map.get(i) for i in indices] != row["stop_ids"]):
            raise ValueError("Native schedule stop indexes do not match the stop catalog.")
        trip_ids.add(trip)
        schedule_map[key] = row
    if trip_ids != set(SCHEDULE_ORACLE):
        raise ValueError("The native timetable catalog is incomplete.")
    for name in ("services", "stops", "schedules"):
        if not _strict_equal(report.get(name + "_after"), report.get(name)):
            problems.add("Native " + name + " catalog changed during the paired experiment.")
    return service_map, stop_map, schedule_map


def _costs(value, stop_map):
    if not isinstance(value, dict) or set(value) != {"access", "egress"}:
        raise ValueError("Missing native access/egress cost maps.")
    maps = {}
    for role in ("access", "egress"):
        rows = value[role]
        if not isinstance(rows, list) or len(rows) != 2:
            raise ValueError("Both fixed stops must occur in each walking cost map.")
        costs = {}
        for row in rows:
            if (not isinstance(row, dict) or row.get("mode") != "WALK"
                    or type(row.get("stop_index")) is not int
                    or row["stop_index"] not in stop_map
                    or row.get("stop_id") != stop_map[row["stop_index"]]
                    or type(row.get("seconds")) is not int or not 0 < row["seconds"] <= 3600
                    or row["stop_index"] in costs):
                raise ValueError("Malformed or duplicate native walking cost.")
            costs[row["stop_index"]] = row["seconds"]
        near = fixture.START_STOP_ID if role == "access" else fixture.END_STOP_ID
        for index, seconds in costs.items():
            # Fixed fixture near-stop walks are about 11 m at 1 m/s. The other
            # stop is over 2.6 km away, outside the twenty-minute trip limit.
            if not ((1 <= seconds <= 30) if stop_map[index] == near else (2500 <= seconds <= 3000)):
                raise ValueError("Walking cost is incompatible with the fixed fixture geometry.")
        maps[role] = costs
    return maps


def _check_request(actual, pair, arm, base):
    expected = dict(base, **request_spec(pair, arm))
    if not _strict_equal(actual, expected):
        raise ValueError("Native request changes more than its service date and equivalent offsets.")
    for key, value in COMMON_REQUEST.items():
        if not _strict_equal(actual.get(key), value):
            raise ValueError("Native request differs from fixed settings: " + key)
    if type(actual.get("suboptimal_minutes")) is not int or actual["suboptimal_minutes"] < 0:
        raise ValueError("Invalid native suboptimal-time setting.")


def _check_chain(chain, sample, request, expected_trip, costs, stop_map, schedules, active):
    if not isinstance(chain, list) or len(chain) != 3:
        raise ValueError("Expected exactly one native access, BUS and egress state.")
    if any(not isinstance(s, dict) or any(type(s.get(k)) is not int for k in STATE_INTS) for s in chain):
        raise ValueError("Malformed native state fields.")
    access, bus, egress = chain
    if expected_trip is None:
        raise ValueError("An arm expected to be empty returned a native path.")
    if (stop_map.get(access["stop"]) != fixture.START_STOP_ID
            or stop_map.get(bus["stop"]) != fixture.END_STOP_ID
            or access["pattern"] != -1 or access["trip"] != -1 or access["round"] != 0
            or bus["round"] != 1 or egress["stop"] != -1
            or egress["pattern"] != -1 or egress["trip"] != -1
            or any(s.get("access_mode") != "WALK" for s in chain)
            or egress.get("egress_mode") != "WALK"):
        raise ValueError("Unexpected native state sequence, stop identity or walking mode.")
    schedule = schedules.get((bus["pattern"], bus["trip"]))
    if schedule is None or schedule["trip_id"] != expected_trip or schedule["service_code"] not in active:
        raise ValueError("Native path uses the wrong trip or inactive service.")
    if bus["board_stop_position"] != 0 or bus["alight_stop_position"] != 1:
        raise ValueError("Native BUS state uses unexpected stop positions.")
    if (access["time"] != sample + costs["access"][access["stop"]]
            or bus["board_time"] != schedule["departures"][0]
            or bus["time"] != schedule["arrivals"][1]
            or bus["board_time"] <= access["time"] + 60
            or egress["time"] != bus["time"] + costs["egress"][bus["stop"]]):
        raise ValueError("Native times disagree with the sample, walking costs, boarding slack or timetable.")
    if not 0 < egress["time"] - sample <= 1200:
        raise ValueError("Native path exceeds the fixed twenty-minute trip limit.")
    # Compare independently declared civil events, not Python itinerary clocks.
    case = next(c for c in fixture.CASES if c["expected_route_id"] == schedule["route_id"])
    if (civil_time(request["native_date"], bus["board_time"]) != case["expected_bus_departure"]
            or civil_time(request["native_date"], bus["time"]) != case["expected_bus_arrival"]):
        raise ValueError("Derived native BUS dates differ from the fixed civil-time oracle.")


def _check_arm(observed, pair, arm, base, original_costs, services, stops, schedules):
    if not isinstance(observed, dict) or observed.get("name") != arm:
        raise ValueError("Missing, extra or reordered native query arm.")
    if observed.get("error"):
        raise ValueError(str(observed["error"]))
    request = observed.get("request")
    _check_request(request, pair, arm, base)
    if not _strict_equal(observed.get("request_after"), request):
        raise ValueError("Native request mutated during routing.")
    for key in ("costs_before", "costs_after"):
        if not _strict_equal(observed.get(key), original_costs):
            raise ValueError("Native access/egress costs changed between paired queries.")
    costs = _costs(original_costs, stops)
    active = observed.get("active_services")
    if (not isinstance(active, list) or any(type(v) is not int or v not in services for v in active)
            or active != sorted(set(active))
            or {services[v] for v in active} != ACTIVE_SERVICES[request["native_date"]]):
        raise ValueError("Native active services disagree with the independent calendar oracle.")
    samples = observed.get("samples")
    if not isinstance(samples, list) or len(samples) != MAX_SAMPLES:
        raise ValueError("The native sample inventory is missing or incomplete.")
    native_keys, civil_keys, chains = [], [], 0
    expected_trip = pair["current_trip_id" if arm == "current_date" else "previous_trip_id"]
    for row in samples:
        if not isinstance(row, dict) or type(row.get("departure_seconds")) is not int:
            raise ValueError("Malformed native sample key.")
        key = row["departure_seconds"]
        if not request["from_time"] <= key < request["to_time"]:
            raise ValueError("Native sample is outside the fixed interval.")
        civil = civil_time(request["native_date"], key)
        if row.get("derived_civil_departure") != civil:
            raise ValueError("Derived sample date does not match its native service-date anchor.")
        paths = row.get("chains")
        if not isinstance(paths, list) or len(paths) > 10:
            raise ValueError("Malformed or unbounded native sample path list.")
        for path in paths:
            _check_chain(path, key, request, expected_trip, costs, stops, schedules, active)
        chains += len(paths)
        native_keys.append(key)
        civil_keys.append(civil)
    if native_keys != sorted(set(native_keys)):
        raise ValueError("Native sampled times are duplicated or unordered.")
    if expected_trip is not None and not chains:
        raise ValueError("The expected native trip was not recovered for this service-date arm.")
    return {"name": arm, "native_samples_checked": len(samples), "native_paths_checked": chains,
            "expected_trip_id": expected_trip, "normalized_sample_times": civil_keys}


def validate_pairs(report: dict) -> list[str]:
    """Recompute acceptance from native observations, preserving the failed baseline."""
    global_problems = _Problems()
    checks = []
    try:
        services, stops, schedules = _catalog(report, global_problems)
    except (KeyError, ValueError, TypeError, OverflowError) as error:
        report["pair_diagnostics"] = []
        return ["Native catalog: " + str(error)]
    observations = report.get("pairs")
    if not isinstance(observations, list) or len(observations) != len(PAIRS):
        global_problems.add("Missing or extra native request pairs.")
    if not isinstance(observations, list):
        observations = []
    for index, pair in enumerate(PAIRS):
        problems = _Problems()
        check = {"id": pair["id"], "arms": [], "normalized_samples_match": False}
        try:
            observed = observations[index] if index < len(observations) else None
            if (not isinstance(observed, dict) or observed.get("id") != pair["id"]
                    or observed.get("civil_departure") != pair["civil_departure"]):
                raise ValueError("Missing, reordered or altered pair identity.")
            if observed.get("error"):
                raise ValueError(str(observed["error"]))
            base = observed.get("base_request")
            if not isinstance(base, dict):
                raise ValueError("Missing original request fields.")
            _check_request(base, pair, "current_date", base)
            if not _strict_equal(observed.get("base_request_after"), base):
                raise ValueError("Original Python-backed native request was mutated.")
            costs = observed.get("costs_before")
            _costs(costs, stops)
            if not _strict_equal(observed.get("costs_after"), costs):
                raise ValueError("Walking costs changed during the pair.")
            arms = observed.get("arms")
            if not isinstance(arms, list) or len(arms) != len(ARMS):
                raise ValueError("Missing or extra native query arms.")
            for arm_index, arm in enumerate(ARMS):
                try:
                    check["arms"].append(_check_arm(arms[arm_index], pair, arm, base, costs,
                                                     services, stops, schedules))
                except (KeyError, ValueError, TypeError, OverflowError) as error:
                    problems.add(arm + ": " + str(error))
            if len(check["arms"]) == 2:
                same = check["arms"][0]["normalized_sample_times"] == check["arms"][1]["normalized_sample_times"]
                check["normalized_samples_match"] = same
                if not same:
                    problems.add("Paired arms sampled different normalized civil times.")
        except (KeyError, ValueError, TypeError, OverflowError) as error:
            problems.add(error)
        check.update(status="failed" if problems.count else "passed",
                     problem_count=problems.count, problems=problems.examples)
        checks.append(check)
        for message in problems.examples:
            global_problems.add(pair["id"] + ": " + message)
    report["pair_diagnostics"] = checks
    report["pairs_passed"] = sum(c["status"] == "passed" for c in checks)
    return global_problems.examples
