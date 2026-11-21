"""Small synthetic OPL cases; no real Melbourne OSM needed."""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_routing_walk_topology.py"
spec = importlib.util.spec_from_file_location("topology_audit", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def test_shared_node_component():
    rows = [
        "w10 v1 dV c0 t2026-01-01T00:00:00Z i0 u Thighway=footway,foot=designated Nn1,n2,n3\n",
        "w11 v1 dV c0 t2026-01-01T00:00:00Z i0 u Thighway=path Nn3,n4\n",
    ]
    report = m.audit_lines(rows, {"entrance": 2, "other": 4, "missing": 5})
    assert report["counts"]["ways_included"] == 2
    assert report["results"][0]["component_nodes"] == 4
    assert report["results"][1]["component_nodes"] == 4
    assert report["results"][2]["result"] == "no_strict_way_node_membership"


def test_excluded_indoor_stairs_areas_and_private():
    rows = [
        "w20 v1 dV c0 t2026-01-01T00:00:00Z i0 u Thighway=corridor,indoor=yes Nn1,n2\n",
        "w21 v1 dV c0 t2026-01-01T00:00:00Z i0 u Thighway=steps Nn2,n3\n",
        "w22 v1 dV c0 t2026-01-01T00:00:00Z i0 u Thighway=pedestrian,area=yes Nn3,n4\n",
        "w23 v1 dV c0 t2026-01-01T00:00:00Z i0 u Thighway=footway,access=private Nn4,n5\n",
        "w24 v1 dV c0 t2026-01-01T00:00:00Z i0 u Thighway=footway Nn5,n6\n",
    ]
    report = m.audit_lines(rows, {"n3": 3, "n5": 5})
    assert report["counts"]["ways_excluded"] == 4
    assert report["results"][0]["result"] == "no_strict_way_node_membership"
    assert report["results"][1]["component_nodes"] == 2


def test_null_entrance_unresolved():
    r = m.audit_lines([], {"flinders": None})
    assert r["results"] == [{"id": "flinders", "node": None, "result": "unresolved_entrance"}]
