"""Focused unit tests that need neither real OSM data nor Osmium."""
import importlib.util
import json
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "review_osm_entrance_candidates.py"
spec = importlib.util.spec_from_file_location("routing_entrance_review", MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_geojsonseq_parses_tagged_points_and_rejects_unrelated_features(tmp_path):
    path = tmp_path / "candidates.geojsonseq"
    records = [
        {"type":"Feature","geometry":{"type":"Point","coordinates":[144.96,-37.81]},"properties":{"@id":17,"entrance":"yes"}},
        {"type":"Feature","geometry":{"type":"Point","coordinates":[144.96,-37.81]},"properties":{"name":"Unrelated"}},
        {"type":"Feature","geometry":{"type":"LineString","coordinates":[[144.96,-37.81],[144.97,-37.82]]},"properties":{"entrance":"yes"}},
    ]
    path.write_text("".join("\x1e" + json.dumps(r) + "\n" for r in records), encoding="utf-8")
    parsed = list(mod.load_features(path))
    assert len(parsed) == 1
    assert parsed[0]["properties"]["@id"] == 17


def test_nearest_only_within_radius_and_never_selects_entrance_automatically():
    stations = [{"id":"s","latitude":-37.81,"longitude":144.96}]
    features = [
        {"latitude":-37.8101,"longitude":144.96,"properties":{"@id":1,"entrance":"yes"}},
        {"latitude":-37.91,"longitude":144.96,"properties":{"@id":2,"entrance":"yes"}},
    ]
    got = mod.nearest_candidates(stations, features, radius_m=100)
    assert len(got["s"]) == 1
    assert got["s"][0]["osm_id"] == "1"
    assert "verified_entrance" not in got["s"][0]


def test_distance_and_radius_boundary():
    assert mod.haversine_m(0,0,0,0) == 0
    assert 100 < mod.haversine_m(0,0,0,0.001) < 120
