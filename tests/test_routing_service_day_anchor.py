"""Independent finite examples for the native date-anchor experiment's oracle."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("routing_anchor_oracle_under_test", ROOT / "scripts/routing_service_day_anchor.py")
m = importlib.util.module_from_spec(spec)
old_path = sys.path.copy()
try:
    sys.path.insert(0, str(ROOT / "scripts"))
    spec.loader.exec_module(m)
finally:
    sys.path[:] = old_path


# These are hand-declared timetable and civil-clock examples. Test data is not
# built from the implementation's oracle, generator, native state or request API.
SCHEDULES = (
    ("SD_TRIP_DAY", "SD_DAY", 0, 29100, 29400),
    ("SD_TRIP_WEDNESDAY", "SD_WEDNESDAY", 1, 32700, 33000),
    ("SD_TRIP_ADDED_DAY", "SD_ADDED_DAY", 2, 36300, 36600),
    ("SD_TRIP_REMOVED_DAY", "SD_REMOVED_DAY", 3, 39900, 40200),
    ("SD_TRIP_CROSS", "SD_CROSS_MIDNIGHT", 0, 86280, 86580),
    ("SD_TRIP_24", "SD_AFTER_24", 0, 87300, 87600),
    ("SD_TRIP_25", "SD_AFTER_25", 0, 90300, 90600),
    ("SD_TRIP_32", "SD_AFTER_32", 0, 117720, 118020),
    ("SD_TRIP_ADDED", "SD_ADDED", 2, 93900, 94200),
    ("SD_TRIP_REMOVED", "SD_REMOVED", 3, 97500, 97800),
)
PAIR_CASES = (
    ("previous_service_24h", "2026-10-14T00:10:00", None, "SD_TRIP_24"),
    ("previous_service_25h", "2026-10-14T01:00:00", None, "SD_TRIP_25"),
    ("previous_service_32h", "2026-10-14T08:37:00", None, "SD_TRIP_32"),
    ("calendar_addition", "2026-10-14T02:00:00", None, "SD_TRIP_ADDED"),
    ("next_date_daytime_control", "2026-10-14T09:00:00", "SD_TRIP_WEDNESDAY", None),
    ("calendar_removal", "2026-10-14T03:00:00", None, None),
    ("inactive_date", "2026-10-15T01:00:00", None, None),
)
COSTS = {
    "access": [{"mode": "WALK", "stop_index": 0, "stop_id": "SMOKE_WEST", "seconds": 12},
               {"mode": "WALK", "stop_index": 1, "stop_id": "SMOKE_EAST", "seconds": 2660}],
    "egress": [{"mode": "WALK", "stop_index": 0, "stop_id": "SMOKE_WEST", "seconds": 2661},
               {"mode": "WALK", "stop_index": 1, "stop_id": "SMOKE_EAST", "seconds": 12}],
}


def request_for(civil, offset):
    instant = datetime.fromisoformat(civil)
    base = instant.replace(hour=0, minute=0, second=0) - timedelta(days=offset)
    seconds = int((instant - base).total_seconds())
    return {
        "native_date": base.date().isoformat(), "from_time": seconds, "to_time": seconds + 360,
        "from_lon": 0.0061, "from_lat": 0.018, "to_lon": 0.0299, "to_lat": 0.018,
        "monte_carlo_draws": 60, "max_trip_duration_minutes": 20, "max_rides": 1,
        "walk_speed_mps": 1.0, "transit_modes": ["BUS"], "access_modes": ["WALK"],
        "egress_modes": ["WALK"], "reverse_search": False, "suboptimal_minutes": 5,
    }


def native_chain(trip_id, sample):
    index, row = next((i, r) for i, r in enumerate(SCHEDULES) if r[0] == trip_id)
    _, _, _, depart, arrive = row
    return [
        {"time": sample + 12, "board_time": -1, "pattern": -1, "trip": -1, "round": 0,
         "stop": 0, "board_stop_position": -1, "alight_stop_position": -1,
         "access_mode": "WALK", "egress_mode": None},
        {"time": arrive, "board_time": depart, "pattern": index, "trip": 0, "round": 1,
         "stop": 1, "board_stop_position": 0, "alight_stop_position": 1,
         "access_mode": "WALK", "egress_mode": None},
        {"time": arrive + 12, "board_time": 0, "pattern": -1, "trip": -1, "round": 0,
         "stop": -1, "board_stop_position": 0, "alight_stop_position": 0,
         "access_mode": "WALK", "egress_mode": "WALK"},
    ]


def valid_report():
    report = {
        "services": [{"service_code": i, "service_id": name} for i, name in
                     enumerate(("SD_TUESDAY", "SD_WEDNESDAY", "SD_ADDED", "SD_REMOVED"))],
        "stops": [{"stop_index": i, "scoped_stop_id": "fixture:" + name, "stop_id": name}
                  for i, name in enumerate(("SMOKE_WEST", "SMOKE_EAST"))],
        "schedules": [{"pattern_index": i, "trip_index": 0, "route_id": route,
                       "scoped_trip_id": "fixture:" + trip, "trip_id": trip, "service_code": code,
                       "stop_indices": [0, 1], "stop_ids": ["SMOKE_WEST", "SMOKE_EAST"],
                       "arrivals": [depart, arrive], "departures": [depart, arrive],
                       "frequency_based": False}
                      for i, (trip, route, code, depart, arrive) in enumerate(SCHEDULES)],
        "pairs": [],
    }
    for name in ("services", "stops", "schedules"):
        report[name + "_after"] = deepcopy(report[name])
    for identifier, civil, current, previous in PAIR_CASES:
        base = request_for(civil, 0)
        pair = {"id": identifier, "civil_departure": civil, "base_request": base,
                "base_request_after": deepcopy(base), "costs_before": deepcopy(COSTS),
                "costs_after": deepcopy(COSTS), "arms": []}
        for offset, (arm_name, expected) in enumerate((("current_date", current), ("previous_date", previous))):
            request = request_for(civil, offset)
            active = {"2026-10-13": [0, 2], "2026-10-14": [1], "2026-10-15": []}[request["native_date"]]
            samples = []
            for delta in range(0, 360, 6):
                key = request["from_time"] + delta
                samples.append({"departure_seconds": key,
                                "derived_civil_departure": (datetime.fromisoformat(civil) + timedelta(seconds=delta)).isoformat(),
                                "chains": [native_chain(expected, key)] if expected and delta == 0 else []})
            pair["arms"].append({"name": arm_name, "request": request, "request_after": deepcopy(request),
                                 "active_services": active, "costs_before": deepcopy(COSTS),
                                 "costs_after": deepcopy(COSTS), "samples": samples})
        report["pairs"].append(pair)
    return report


@pytest.fixture
def native_report():
    return valid_report()


def test_equivalent_native_anchors_keep_full_extended_seconds():
    pair = next(p for p in m.PAIRS if p["id"] == "previous_service_25h")
    assert m.request_spec(pair, "current_date") == {"native_date": "2026-10-14", "from_time": 3600, "to_time": 3960}
    assert m.request_spec(pair, "previous_date") == {"native_date": "2026-10-13", "from_time": 90000, "to_time": 90360}
    assert m.civil_time("2026-10-13", 90300) == "2026-10-14T01:05:00"
    assert m.civil_time("2026-10-13", 118020) == "2026-10-14T08:47:00"


@pytest.mark.parametrize("native_date,seconds", [("20261013", 90000), ("2026-10-13", True),
                                                ("2026-10-13", -1), ("2026-10-13", 90000.0),
                                                ("2026-10-13", 300000), ("2026-13-13", 0)])
def test_invalid_anchor_or_native_offset_is_rejected(native_date, seconds):
    with pytest.raises(ValueError):
        m.civil_time(native_date, seconds)


def test_valid_pair_examples_expose_both_recovery_and_current_day_loss_without_mutation(native_report):
    before = deepcopy(native_report)
    assert m.validate_pairs(native_report) == []
    assert native_report["pairs_passed"] == 7
    assert all(c["status"] == "passed" and c["normalized_samples_match"] is True
               for c in native_report["pair_diagnostics"])
    assert [[a["native_paths_checked"] for a in p["arms"]] for p in native_report["pair_diagnostics"]] == [
        [0, 1], [0, 1], [0, 1], [0, 1], [1, 0], [0, 0], [0, 0],
    ]
    assert all(native_report[key] == value for key, value in before.items())


def test_both_empty_arms_do_not_pass_a_positive_recovery_probe(native_report):
    native_report["pairs"][1]["arms"][1]["samples"][0]["chains"] = []
    assert m.validate_pairs(native_report)
    assert native_report["pair_diagnostics"][1]["status"] == "failed"
    assert native_report["pairs_passed"] == 6


@pytest.mark.parametrize("change", ["missing", "duplicate", "reordered", "extra", "not_list"])
def test_every_fixed_pair_must_be_present_once(native_report, change):
    if change == "missing":
        native_report["pairs"].pop()
    elif change == "duplicate":
        native_report["pairs"][1] = deepcopy(native_report["pairs"][0])
    elif change == "reordered":
        native_report["pairs"].reverse()
    elif change == "extra":
        native_report["pairs"].append(deepcopy(native_report["pairs"][0]))
    else:
        native_report["pairs"] = {}
    assert m.validate_pairs(native_report)
    assert len(native_report["pair_diagnostics"]) == 7


@pytest.mark.parametrize("name", ["services", "stops", "schedules"])
def test_native_catalog_mutation_cannot_be_hidden_by_valid_paths(native_report, name):
    native_report[name + "_after"] = []
    assert m.validate_pairs(native_report)


@pytest.mark.parametrize("change", ["modulo_day", "wrong_service", "wrong_route", "wrong_stop", "missing_trip", "frequency", "duplicate_trip"])
def test_imported_schedule_is_checked_against_independent_oracle(native_report, change):
    row = native_report["schedules"][6]
    if change == "modulo_day":
        row["departures"] = [3900, 4200]
        row["arrivals"] = [3900, 4200]
    elif change == "wrong_service":
        row["service_code"] = 1
    elif change == "wrong_route":
        row["route_id"] = "SD_WEDNESDAY"
    elif change == "wrong_stop":
        row["stop_indices"].reverse()
    elif change == "missing_trip":
        native_report["schedules"].pop()
    elif change == "frequency":
        row["frequency_based"] = True
    else:
        native_report["schedules"].append(deepcopy(row))
    native_report["schedules_after"] = deepcopy(native_report["schedules"])
    assert m.validate_pairs(native_report)


@pytest.mark.parametrize("change", ["no_keys", "too_few", "duplicate", "outside", "shifted_pair", "wrong_derived_date", "boolean_key", "missing_chains"])
def test_actual_native_sample_keys_are_complete_and_civil_equivalent(native_report, change):
    arm = native_report["pairs"][1]["arms"][1]
    samples = arm["samples"]
    if change == "no_keys":
        arm["samples"] = []
    elif change == "too_few":
        samples.pop()
    elif change == "duplicate":
        samples[-1] = deepcopy(samples[-2])
    elif change == "outside":
        samples[-1]["departure_seconds"] = 90360
        samples[-1]["derived_civil_departure"] = "2026-10-14T01:06:00"
    elif change == "shifted_pair":
        samples[-1]["departure_seconds"] = 90355
        samples[-1]["derived_civil_departure"] = "2026-10-14T01:05:55"
    elif change == "wrong_derived_date":
        samples[0]["derived_civil_departure"] = "2026-10-15T01:00:00"
    elif change == "boolean_key":
        samples[0]["departure_seconds"] = True
    else:
        samples[0].pop("chains")
    assert m.validate_pairs(native_report)
    assert native_report["pair_diagnostics"][1]["status"] == "failed"


@pytest.mark.parametrize("where", ["pair_after", "arm_before", "arm_after"])
def test_paired_walking_costs_must_be_identical(native_report, where):
    pair = native_report["pairs"][1]
    costs = pair["costs_after"] if where == "pair_after" else pair["arms"][1]["costs_" + where.split("_")[1]]
    costs["access"][0]["seconds"] += 1
    assert m.validate_pairs(native_report)


def test_even_equal_maps_cannot_introduce_zero_cost_or_shortcut_far_stop(native_report):
    pair = native_report["pairs"][1]
    for costs in [pair["costs_before"], pair["costs_after"], *[a[k] for a in pair["arms"] for k in ("costs_before", "costs_after")]]:
        costs["access"][1]["seconds"] = 1
    assert m.validate_pairs(native_report)


@pytest.mark.parametrize("change", ["changed_date", "wrapped_time", "changed_coordinates", "changed_modes", "unrestored_original", "mutated_clone", "boolean_draw_count"])
def test_request_clones_only_change_service_date_and_corresponding_offsets(native_report, change):
    pair = native_report["pairs"][1]
    arm = pair["arms"][1]
    if change == "unrestored_original":
        pair["base_request_after"]["from_time"] = 90000
    elif change == "mutated_clone":
        arm["request_after"]["from_time"] += 1
    else:
        field, value = {"changed_date": ("native_date", "2026-10-14"),
                        "wrapped_time": ("from_time", 3600),
                        "changed_coordinates": ("from_lat", 0.02),
                        "changed_modes": ("transit_modes", ["BUS", "RAIL"]),
                        "boolean_draw_count": ("monte_carlo_draws", True)}[change]
        arm["request"][field] = value
        arm["request_after"][field] = value
    assert m.validate_pairs(native_report)


@pytest.mark.parametrize("which,active", [(0, [0, 1, 2]), (1, [0, 2, 3]), (1, [0]), (1, [True, 2])])
def test_calendar_set_cannot_merge_days_lose_addition_or_restore_removed_service(native_report, which, active):
    native_report["pairs"][1]["arms"][which]["active_services"] = active
    assert m.validate_pairs(native_report)


@pytest.mark.parametrize("change", ["wrong_trip", "wrong_stop", "wrong_order", "truncated", "extra_transfer", "wrong_board_time", "wrong_arrival", "python_egress_pad", "access_cost_mismatch", "boolean_time", "wrong_mode"])
def test_raw_state_chain_must_match_sample_native_costs_and_exact_trip(native_report, change):
    chain = native_report["pairs"][1]["arms"][1]["samples"][0]["chains"][0]
    if change == "wrong_trip":
        chain[1]["pattern"] = 5
    elif change == "wrong_stop":
        chain[1]["stop"] = 0
    elif change == "wrong_order":
        chain.reverse()
    elif change == "truncated":
        chain.pop()
    elif change == "extra_transfer":
        chain.insert(1, deepcopy(chain[0]))
    elif change == "wrong_board_time":
        chain[1]["board_time"] -= 86400
    elif change == "wrong_arrival":
        chain[1]["time"] += 1
    elif change == "python_egress_pad":
        chain[2]["time"] += 60
    elif change == "access_cost_mismatch":
        chain[0]["time"] += 1
    elif change == "boolean_time":
        chain[1]["time"] = True
    else:
        chain[2]["egress_mode"] = "BICYCLE"
    assert m.validate_pairs(native_report)


def test_ordinary_current_date_service_must_remain_lost_under_previous_anchor(native_report):
    previous_arm = native_report["pairs"][4]["arms"][1]
    sample = previous_arm["samples"][0]
    sample["chains"] = [native_chain("SD_TRIP_WEDNESDAY", sample["departure_seconds"])]
    assert m.validate_pairs(native_report)
    assert native_report["pair_diagnostics"][4]["status"] == "failed"


def test_empty_calendar_control_with_query_exception_cannot_pass(native_report):
    native_report["pairs"][5]["arms"][1]["error"] = "native query threw before producing evidence"
    assert m.validate_pairs(native_report)
    assert native_report["pair_diagnostics"][5]["status"] == "failed"


def test_exactly_sixty_seconds_of_boarding_slack_is_not_boardable(native_report):
    # The pinned native router requires departure > access arrival + 60, not >=.
    # At 25:03:48, the 12-second access ends at 25:04:00; a 25:05 departure
    # therefore lies exactly on the excluded boundary.
    samples = native_report["pairs"][1]["arms"][1]["samples"]
    samples[0]["chains"] = []
    sample = samples[38]
    assert sample["departure_seconds"] == 90228
    sample["chains"] = [native_chain("SD_TRIP_25", sample["departure_seconds"])]
    assert m.validate_pairs(native_report)
    assert native_report["pair_diagnostics"][1]["status"] == "failed"
