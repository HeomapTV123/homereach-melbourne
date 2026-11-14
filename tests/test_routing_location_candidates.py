"""Unit tests for read-only station candidate discovery using fictional feed data."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tempfile
from zipfile import ZipFile
import importlib.util

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/inspect_routing_location_candidates.py"
SPEC = importlib.util.spec_from_file_location("inspect_routing_location_candidates", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def make_fixture(root: Path):
    archive = root / "data/raw/transport/gtfs.zip"
    archive.parent.mkdir(parents=True)
    nested = io.BytesIO()
    with ZipFile(nested, "w") as z:
        z.writestr("stops.txt", "stop_id,stop_name,stop_lat,stop_lon,location_type,parent_station\n"
                   "10,Footscray Station,-37.80,144.89,1,\n"
                   "11,Footscray Platform 1,-37.801,144.891,0,10\n"
                   "12,Coburg Station,-37.74,144.96,1,\n")
    with ZipFile(archive, "w") as z:
        z.writestr("2/google_transit.zip", nested.getvalue())
    config = {
        "gtfs_archive": "data/raw/transport/gtfs.zip",
        "gtfs_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "feed_id": "2",
        "candidates": [
            {"id": "footscray", "role": "origin", "place": "Footscray", "status": "review", "match_text": "Footscray"},
            {"id": "coburg", "role": "origin", "place": "Coburg", "status": "review", "match_text": "Coburg"},
            {"id": "dandenong", "role": "origin", "place": "Dandenong", "status": "review", "match_text": "Dandenong"},
        ],
    }
    return config


def test_candidates_retain_original_ids_and_distinguish_platforms():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        config = make_fixture(root)
        before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        results = module.read_candidate_stops(root, config)
        assert [len(x["matched_stops"]) for x in results] == [2, 1, 0]
        assert results[0]["matched_stops"][0]["stop_key"] == "2:11" or results[0]["matched_stops"][0]["stop_key"] == "2:10"
        assert {x["stop_key"] for x in results[0]["matched_stops"]} == {"2:10", "2:11"}
        assert results[1]["matched_stops"][0]["latitude"] == -37.74
        assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_modified_archives_and_escaping_paths_are_rejected():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        config = make_fixture(root)
        with (root / config["gtfs_archive"]).open("ab") as handle:
            handle.write(b"changed")
        try:
            module.read_candidate_stops(root, config)
        except ValueError as e:
            assert "hash" in str(e)
        else:
            raise AssertionError("Modified archive should be rejected")
        config["gtfs_archive"] = "../outside.zip"
        try:
            module.read_candidate_stops(root, config)
        except ValueError as e:
            assert "project-relative" in str(e)
        else:
            raise AssertionError("Escaping path should be rejected")
