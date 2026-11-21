"""Fictional OPL evidence for strict-component boundary review, never real routes."""
import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_routing_walk_topology.py"
spec = importlib.util.spec_from_file_location("walk_boundary_audit", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def way(way_id, refs, tags="highway=footway"):
    nodes = ",".join(f"n{node}" for node in refs)
    return f"w{way_id} v1 dV c0 t2026-01-01T00:00:00Z i0 u T{tags} N{nodes}\n"


def review(rows, targets=None, selected=None, limit=20):
    targets = {"entrance": 1} if targets is None else targets
    selected = list(targets) if selected is None else selected
    state = m.build_strict_state(iter(rows), targets, validate_ways=True)
    return m.scan_boundary_lines(state, iter(rows), selected, limit=limit)


def test_excluded_way_before_graph_and_touching_non_entrance_node():
    rows = [way(20, [3, 10], "highway=steps"), way(1, [1, 2, 3]), way(2, [10, 11])]
    report = review(rows)
    strict = report["strict_audit"]
    assert strict["counts"] == {"ways_seen": 3, "ways_excluded": 1, "ways_included": 2}
    assert strict["results"] == [{"id": "entrance", "node": 1,
                                   "result": "strict_component_found", "incident_ways": [1],
                                   "component_nodes": 3}]
    row = report["boundary_review"]["results"][0]
    assert row["excluded_ways_touching"] == 1
    assert row["component_id_min_node"] == 1
    example = row["examples"][0]
    assert example["shared_component_nodes"] == [3]
    assert example["other_strict_components"] == [
        {"component_id_min_node": 10, "component_nodes": 2, "shared_nodes": [10]}]
    assert example["relationship"] == "touches_other_strict_components"
    assert example["exclusion_reasons"] == ["highway_outside_strict_subset"]


def test_every_matching_exclusion_reason_is_reported():
    tags = "highway=corridor,area=yes,indoor=yes,foot=private,access=customers,tunnel=building_passage,level=1,layer=2"
    result = review([way(1, [1, 2]), way(9, [2, 3], tags)])["boundary_review"]["results"][0]
    expected = ["highway_outside_strict_subset", "area_yes", "indoor_yes", "foot_restricted",
                "access_restricted", "tunnel_present", "level_outside_ground", "layer_outside_ground"]
    assert result["examples"][0]["exclusion_reasons"] == expected
    assert result["exclusion_reason_counts"] == dict.fromkeys(expected, 1)
    assert result["excluded_ways_touching"] == 1


@pytest.mark.parametrize("tags, expected", [
    ({"highway": "path", "level": "0.0", "layer": "0", "tunnel": "no"}, True),
    ({"highway": "living_street", "foot": "designated"}, True),
    ({"highway": "footway", "access": "private", "foot": "yes"}, False),
    ({"highway": "footway", "foot": "customers"}, False),
    ({"highway": "footway", "layer": "0.0"}, False),
    ({"highway": "footway", "level": "0;1"}, False),
    ({"highway": "residential", "foot": "yes"}, False),
    ({}, False),
])
def test_original_strict_policy_is_preserved(tags, expected):
    assert m.eligible(tags) is expected


def test_outside_nodes_do_not_become_components_and_can_coexist_with_other_components():
    rows = [way(1, [1, 2, 3]), way(2, [7, 8]), way(9, [1, 3, 7, 99, 99], "highway=steps")]
    state = m.build_strict_state(rows, {"entrance": 1, "outside": 99}, validate_ways=True)
    original_nodes = set(state.components.parent)
    original_sizes = sorted(state.components.size.values())
    result = m.scan_boundary_lines(state, rows, ["entrance", "outside"])
    available, unknown = result["boundary_review"]["results"]
    example = available["examples"][0]
    assert example["shared_component_nodes"] == [1, 3]
    assert example["nodes_outside_strict_graph_count"] == 1
    assert example["other_strict_components"][0]["shared_nodes"] == [7]
    assert available["excluded_ways_touching"] == 1
    assert set(state.components.parent) == original_nodes
    assert sorted(state.components.size.values()) == original_sizes
    assert unknown["result"] == "no_strict_way_node_membership"
    assert unknown["boundary_scan"] == "not_available"
    assert "excluded_ways_touching" not in unknown


def test_does_not_follow_chains_of_excluded_ways():
    rows = [way(1, [1, 2]), way(2, [10, 11]),
            way(20, [2, 99], "highway=steps"), way(21, [99, 10], "highway=steps")]
    result = review(rows)["boundary_review"]["results"][0]
    assert result["excluded_ways_touching"] == 1
    assert [example["way_id"] for example in result["examples"]] == [20]
    assert result["examples"][0]["relationship"] == "extends_outside_strict_graph"
    assert result["examples"][0]["other_strict_components"] == []


def test_same_component_area_ring_is_evidence_without_adding_edges():
    rows = [way(1, [1, 2, 3]), way(20, [1, 3, 1], "highway=pedestrian,area=yes")]
    result = review(rows)["boundary_review"]["results"][0]
    example = result["examples"][0]
    assert result["component_nodes"] == 3
    assert example["relationship"] == "within_same_strict_component"
    assert example["shared_component_nodes"] == [1, 3]
    assert example["nodes_outside_strict_graph_count"] == 0
    assert example["other_strict_components"] == []


def test_limit_preserves_complete_counts_and_examples_are_order_independent():
    rows = [way(10, [8, 9]), way(11, [1, 2]), way(12, [2, 3]),
            way(300, [3, 8], "highway=steps"), way(100, [3, 9], "highway=corridor,indoor=yes"),
            way(5, [1, 50], "highway=footway,access=private"),
            way(6, [2, 51], "highway=footway,tunnel=yes")]
    first = review(rows, limit=2)["boundary_review"]
    second = review(list(reversed(rows)), limit=2)["boundary_review"]
    assert first == second
    row = first["results"][0]
    assert row["excluded_ways_touching"] == 4
    assert row["examples_shown"] == 2
    assert row["examples_omitted"] == 2
    assert [example["way_id"] for example in row["examples"]] == [100, 300]
    assert row["relationship_counts"] == {"touches_other_strict_components": 2, "extends_outside_strict_graph": 2}
    assert sum(row["exclusion_reason_counts"].values()) == 5


def test_same_component_selected_twice_by_distinct_locations_has_consistent_evidence():
    rows = [way(1, [1, 2, 3]), way(20, [3, 99], "highway=steps")]
    result = review(rows, {"a": 1, "b": 2})["boundary_review"]["results"]
    assert [row["id"] for row in result] == ["a", "b"]
    assert [row["component_id_min_node"] for row in result] == [1, 1]
    assert [row["excluded_ways_touching"] for row in result] == [1, 1]
    assert result[0]["examples"] == result[1]["examples"]


def test_null_entrance_stays_unresolved():
    result = review([], {"flinders": None})
    assert result["boundary_review"]["results"] == [
        {"id": "flinders", "node": None, "result": "unresolved_entrance", "boundary_scan": "not_available"}]
    assert result["verification"]["ways_scanned_each_pass"] == 0


def test_raw_opl_tags_are_preserved_for_review():
    row = review([way(1, [1, 2]), way(20, [2, 3], "highway=steps,name=Station%20%stairs")])
    assert row["boundary_review"]["results"][0]["examples"][0]["tags_opl"]["name"] == "Station%20%stairs"


@pytest.mark.parametrize("bad_row", [
    "wbad Thighway=steps Nn1,n2\n", "w5 Thighway=steps N\n",
    "w5 Thighway=steps N1,n2\n", "w5 Thighway=steps Nn1,,n2\n",
    "w5 Thighway=steps,highway=footway Nn1,n2\n", "w5 Thighway=steps,bad_tag Nn1,n2\n",
])
def test_malformed_way_fails_closed_for_boundary_mode(bad_row):
    with pytest.raises(ValueError, match="Malformed"):
        m.build_strict_state([bad_row], {"a": 1}, validate_ways=True)


def test_duplicate_way_ids_fail_closed():
    rows = [way(1, [1, 2]), way(1, [2, 3], "highway=steps")]
    with pytest.raises(ValueError, match="Duplicate OPL way ID"):
        m.build_strict_state(rows, {"a": 1}, validate_ways=True)


@pytest.mark.parametrize("change", ["missing", "changed_tags", "duplicate"])
def test_second_pass_change_discards_report(change):
    rows = [way(1, [1, 2]), way(20, [2, 3], "highway=steps")]
    state = m.build_strict_state(rows, {"a": 1}, validate_ways=True)
    changed = {"missing": rows[:1], "changed_tags": [rows[0], way(20, [2, 3], "highway=corridor")],
               "duplicate": rows + [rows[1]]}[change]
    with pytest.raises(ValueError, match="changed between passes|Duplicate OPL way ID"):
        m.scan_boundary_lines(state, changed, ["a"])


def test_boundary_scan_rejects_unvalidated_first_pass():
    state = m.build_strict_state([way(1, [1, 2])], {"a": 1})
    with pytest.raises(ValueError, match="validated first pass"):
        m.scan_boundary_lines(state, [], ["a"])


@pytest.mark.parametrize("selected,limit", [([], 20), (["missing"], 20), (["a", "a"], 20),
                                          (["a"], 0), (["a"], True)])
def test_invalid_boundary_request_is_rejected(selected, limit):
    state = m.build_strict_state([way(1, [1, 2])], {"a": 1}, validate_ways=True)
    with pytest.raises(ValueError):
        m.scan_boundary_lines(state, [], selected, limit=limit)
