"""Independent synthetic walking checks require the intended endpoints and length.

These cases use explicit coordinates from the reviewed fictional grid. They
exercise the oracle without importing routing, GIS, or JVM packages.
"""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/routing_walk_geometry.py"
SPEC = importlib.util.spec_from_file_location("routing_walk_geometry_under_test", SCRIPT)
m = importlib.util.module_from_spec(SPEC)
previous_path = sys.path.copy()
try:
    sys.path.insert(0, str(SCRIPT.parent))
    SPEC.loader.exec_module(m)
finally:
    sys.path[:] = previous_path


def walking_leg(coordinates, distance, *, segment=0, option=0):
    return {
        "from_id": "synthetic_origin", "to_id": "synthetic_destination",
        "mode": "WALK", "option": option, "segment": segment,
        "distance_m": distance,
        "geometry": {"type": "LineString", "coordinates": coordinates},
    }


@pytest.fixture
def correct_report():
    return {
        "geometry_crs": {"walking": "EPSG:4326", "transit": "EPSG:4326"},
        "walking": [walking_leg([
            [0.0061, 0.018], [0.012, 0.018], [0.018, 0.018],
            [0.024, 0.018], [0.0299, 0.018],
        ], 2646.4391235439543)],
        "transit": [
            walking_leg([[0.0061, 0.018], [0.006, 0.018]], 11.119492115730884),
            {"mode": "BUS", "option": 0, "segment": 1, "distance_m": 2668.6781077754163,
             "geometry": {"type": "LineString", "coordinates": [[0.006, 0.018], [0.030, 0.018]]},
             "agency_id": "SMOKE", "route_id": "SMOKE_BUS",
             "start_stop_id": "SMOKE_WEST", "end_stop_id": "SMOKE_EAST"},
            walking_leg([[0.030, 0.018], [0.0299, 0.018]], 11.119492115730798, segment=2),
        ],
    }


def test_complete_reference_walks_pass_and_raw_input_is_unchanged(correct_report):
    original = deepcopy(correct_report)
    result = m.audit_walk_geometry(correct_report)
    assert result["status"] == "passed"
    assert result["problems"] == []
    assert result["counts"]["walking_legs_checked"] == 3
    assert all(value == 0 for key, value in result["counts"].items()
               if key != "walking_legs_checked")
    assert result["reference_walks"]["access"]["distance_m"] == pytest.approx(11.119492115730884, abs=0.001)
    assert result["reference_walks"]["egress"]["distance_m"] == pytest.approx(11.119492115730798, abs=0.001)
    assert correct_report == original
    json.dumps(result, allow_nan=False)


def test_reversed_lines_preserve_endpoint_coverage_and_length(correct_report):
    for row in correct_report["walking"] + correct_report["transit"]:
        if row["mode"] == "WALK":
            row["geometry"]["coordinates"].reverse()
    result = m.audit_walk_geometry(correct_report)
    assert result["status"] == "passed"
    assert result["problems"] == []
    assert {row["orientation"] for row in result["observations"]} == {"reverse"}


@pytest.mark.parametrize("location,coordinates,distance", [
    ("direct", [[0.006, 0.018], [0.012, 0.018], [0.018, 0.018],
                [0.024, 0.018], [0.030, 0.018], [0.036, 0.018]], 2656.089),
    ("access", [[0.012, 0.018], [0.006, 0.018]], 11.1),
    ("egress", [[0.030, 0.018], [0.036, 0.018]], 677.897),
])
def test_actual_full_edge_shapes_fail_even_with_positive_reported_distance(
    correct_report, location, coordinates, distance,
):
    row = correct_report["walking"][0] if location == "direct" else correct_report["transit"][0 if location == "access" else 2]
    row["geometry"]["coordinates"] = coordinates
    row["distance_m"] = distance
    original = deepcopy(correct_report)
    result = m.audit_walk_geometry(correct_report)
    assert result["status"] == "failed"
    assert result["problems"]
    assert result["counts"]["endpoint_mismatches"] == 1
    assert result["counts"]["geometry_distance_mismatches"] == 1
    assert correct_report == original


def test_reported_long_egress_fails_even_when_geometry_has_correct_endpoints(correct_report):
    correct_report["transit"][2]["distance_m"] = 677.897
    result = m.audit_walk_geometry(correct_report)
    assert result["status"] == "failed"
    assert result["problems"]
    assert result["counts"]["endpoint_mismatches"] == 0
    assert result["counts"]["geometry_distance_mismatches"] == 1
    assert result["counts"]["shortest_distance_mismatches"] == 1


def test_detour_with_correct_endpoints_cannot_be_called_the_shortest_reference_walk(correct_report):
    # Backtrack along a real grid edge, then return to the intended stop.
    correct_report["transit"][0]["geometry"]["coordinates"] = [
        [0.0061, 0.018], [0.012, 0.018], [0.006, 0.018],
    ]
    correct_report["transit"][0]["distance_m"] = 1323.219561772
    result = m.audit_walk_geometry(correct_report)
    assert result["status"] == "failed"
    assert result["problems"]


@pytest.mark.parametrize("geometry", [
    None,
    {},
    {"type": "Point", "coordinates": [0.0061, 0.018]},
    {"type": "LineString", "coordinates": []},
    {"type": "LineString", "coordinates": [[0.0061, 0.018]]},
    {"type": "LineString", "coordinates": [[0.0061, 0.018], [float("nan"), 0.018]]},
    {"type": "LineString", "coordinates": [[0.0061, 0.018], [float("inf"), 0.018]]},
    {"type": "LineString", "coordinates": [[True, 0.018], [0.006, 0.018]]},
    {"type": "LineString", "coordinates": [["0.0061", 0.018], [0.006, 0.018]]},
    {"type": "LineString", "coordinates": [[0.0061, 0.018], [181.0, 0.018]]},
])
def test_malformed_geometry_is_a_serializable_failure(correct_report, geometry):
    correct_report["transit"][0]["geometry"] = geometry
    result = m.audit_walk_geometry(correct_report)
    assert result["status"] == "failed"
    assert result["problems"]
    json.dumps(result, allow_nan=False)


def test_missing_geometry_is_not_evidence_of_a_valid_walk(correct_report):
    del correct_report["transit"][0]["geometry"]
    result = m.audit_walk_geometry(correct_report)
    assert result["status"] == "failed"


@pytest.mark.parametrize("crs", [None, "EPSG:3857", "", 4326])
def test_crs_must_be_explicitly_verified_for_every_result_frame(correct_report, crs):
    correct_report["geometry_crs"]["transit"] = crs
    result = m.audit_walk_geometry(correct_report)
    assert result["status"] == "failed"
    assert result["problems"]


def test_missing_crs_cannot_be_assumed(correct_report):
    del correct_report["geometry_crs"]
    assert m.audit_walk_geometry(correct_report)["status"] == "failed"


@pytest.mark.parametrize("distance", [None, 0, -1, True, float("nan"), float("inf"), "11.1"])
def test_invalid_reported_distance_is_a_serializable_failure(correct_report, distance):
    correct_report["transit"][0]["distance_m"] = distance
    result = m.audit_walk_geometry(correct_report)
    assert result["status"] == "failed"
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("change", ["no_direct", "no_access", "no_egress", "unknown_walk_segment"])
def test_absent_or_unclassifiable_required_walks_fail(correct_report, change):
    if change == "no_direct":
        correct_report["walking"] = []
    elif change == "no_access":
        del correct_report["transit"][0]
    elif change == "no_egress":
        del correct_report["transit"][2]
    else:
        correct_report["transit"][2]["segment"] = 3
    result = m.audit_walk_geometry(correct_report)
    assert result["status"] == "failed"
    assert result["problems"]


def test_failure_in_one_alternative_is_not_hidden_by_another(correct_report):
    extra = deepcopy(correct_report["transit"])
    for row in extra:
        row["option"] = 1
    extra[2]["geometry"]["coordinates"] = [[0.030, 0.018], [0.036, 0.018]]
    correct_report["transit"].extend(extra)
    original = deepcopy(correct_report)
    assert m.audit_walk_geometry(correct_report)["status"] == "failed"
    assert correct_report == original


def test_unreviewed_xml_cannot_provide_a_passing_reference(correct_report, tmp_path, monkeypatch):
    changed = tmp_path / "changed-streets.osm"
    changed.write_text(m.REFERENCE_XML.read_text(encoding="utf-8").replace(
        '<tag k="foot" v="yes"', '<tag k="foot" v="no"', 1,
    ), encoding="utf-8")
    monkeypatch.setattr(m, "REFERENCE_XML", changed)
    result = m.audit_walk_geometry(correct_report)
    assert result["status"] == "failed"
    assert result["problems"]


@pytest.mark.parametrize("extra_metres,expected_status", [(1.99, "passed"), (2.01, "failed")])
def test_short_leg_distance_allowance_is_two_metres(correct_report, extra_metres, expected_status):
    correct_report["transit"][0]["distance_m"] += extra_metres
    assert m.audit_walk_geometry(correct_report)["status"] == expected_status


def test_long_walk_distance_allowance_is_not_one_percent(correct_report):
    # A half-percent excess is outside the declared 0.2% allowance even though
    # the geometry still covers precisely the intended direct walking path.
    correct_report["walking"][0]["distance_m"] *= 1.005
    result = m.audit_walk_geometry(correct_report)
    assert result["status"] == "failed"
    assert result["counts"]["shortest_distance_mismatches"] == 1


def test_straight_reference_requires_an_actual_walkable_edge(correct_report, tmp_path, monkeypatch):
    root = ET.fromstring(m.REFERENCE_XML.read_bytes())
    for way in root.findall("way"):
        if {int(node.attrib["ref"]) for node in way.findall("nd")} == {23, 24}:
            for tag in way.findall("tag"):
                if tag.attrib["k"] == "foot":
                    tag.set("v", "no")
            break
    else:
        pytest.fail("Reviewed fixture is missing its expected west horizontal edge.")
    changed_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"
    changed = tmp_path / "closed-west-edge.osm"
    changed.write_bytes(changed_bytes)
    # Match the source check so this exercises the separate reachability proof.
    monkeypatch.setattr(m, "REFERENCE_XML", changed)
    monkeypatch.setattr(m.fixture, "street_xml", lambda: changed_bytes)
    result = m.audit_walk_geometry(correct_report)
    assert result["status"] == "failed"
    assert result["problems"]


def test_nonempty_collection_of_malformed_rows_does_not_pass_vacuously(correct_report):
    correct_report["transit"] = [None, {}]
    result = m.audit_walk_geometry(correct_report)
    assert result["status"] == "failed"
    assert result["counts"]["malformed_rows"] == 2
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("identifier", ["option", "segment"])
def test_boolean_identifiers_are_not_treated_as_integer_sequence_values(correct_report, identifier):
    correct_report["transit"][0][identifier] = False
    result = m.audit_walk_geometry(correct_report)
    assert result["status"] == "failed"
    assert result["counts"]["malformed_rows"] == 1
