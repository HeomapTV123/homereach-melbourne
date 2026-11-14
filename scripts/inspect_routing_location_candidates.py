"""Find candidate stop locations in the pinned nested GTFS train feed.

This read-only utility does not select entrance locations or calculate routes.
It requires the audited archive SHA-256 before reading stop records.
"""
from __future__ import annotations

import argparse
import csv
from hashlib import sha256
from io import TextIOWrapper
import json
from pathlib import Path
from tempfile import SpooledTemporaryFile
import shutil
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/routing_location_candidates.json"
REQUIRED = {"stop_id", "stop_name", "stop_lat", "stop_lon", "location_type", "parent_station"}


def source_hash(path: Path) -> str:
    h = sha256()
    with path.open("rb") as f:
        while block := f.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def read_candidate_stops(root: Path, config: dict) -> list[dict]:
    """Read named candidates, retaining original feed-scoped GTFS fields."""
    root = root.resolve()
    relative = Path(config["gtfs_archive"])
    if relative.is_absolute() or ".." in relative.parts or "\\" in config["gtfs_archive"]:
        raise ValueError("GTFS path must be project-relative with forward slashes")
    archive_path = (root / relative).resolve()
    if not archive_path.is_relative_to(root):
        raise ValueError("GTFS archive resolves outside project")
    if source_hash(archive_path) != config["gtfs_sha256"]:
        raise ValueError("GTFS archive hash differs from pinned input")
    feed_member = f"{config['feed_id']}/google_transit.zip"
    with ZipFile(archive_path) as outer:
        if outer.namelist().count(feed_member) != 1:
            raise ValueError(f"Expected exactly one {feed_member}")
        with SpooledTemporaryFile(max_size=16 * 1024 * 1024) as spool:
            with outer.open(feed_member) as src:
                shutil.copyfileobj(src, spool)
            spool.seek(0)
            with ZipFile(spool) as inner:
                if inner.namelist().count("stops.txt") != 1:
                    raise ValueError("Expected exactly one stops.txt")
                with inner.open("stops.txt") as source:
                    reader = csv.DictReader(TextIOWrapper(source, encoding="utf-8-sig", newline=""))
                    if not reader.fieldnames or not REQUIRED.issubset(reader.fieldnames):
                        raise ValueError("Missing GTFS stop columns")
                    stops = list(reader)
    result = []
    for candidate in config["candidates"]:
        term = candidate["match_text"].casefold()
        matches = []
        for stop in stops:
            name = (stop.get("stop_name") or "").casefold()
            if term not in name:
                continue
            try:
                lat, lon = float(stop["stop_lat"]), float(stop["stop_lon"])
            except (TypeError, ValueError) as exc:
                raise ValueError("Matched stop has invalid coordinates") from exc
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("Matched stop has coordinates outside WGS84 bounds")
            matches.append({
                "stop_key": f"{config['feed_id']}:{stop['stop_id']}",
                "stop_id": stop["stop_id"], "name": stop["stop_name"],
                "latitude": lat, "longitude": lon,
                "location_type": stop["location_type"],
                "parent_station": stop["parent_station"],
            })
        matches.sort(key=lambda x: (x["name"].casefold(), x["stop_id"]))
        result.append({"candidate_id": candidate["id"], "role": candidate["role"],
                       "place": candidate["place"], "status": candidate["status"],
                       "matched_stops": matches})
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root", type=Path, default=ROOT)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    root = args.project_root.resolve()
    config = json.loads((root / "config/routing_location_candidates.json").read_text(encoding="utf-8"))
    if (config.get("schema_version"), config.get("feed_id"), config.get("crs")) != (1, "2", "EPSG:4326"):
        raise ValueError("Unexpected candidate config contract")
    result = read_candidate_stops(root, config)
    if args.json:
        print(json.dumps({"status": "candidate_review_only", "service_date": config["service_date"],
                          "crs": config["crs"], "candidates": result}, indent=2))
    else:
        print("ROUTING LOCATION CANDIDATES — REVIEW ONLY")
        print(f"Train feed 2 | {config['service_date']} | {config['crs']}")
        for group in result:
            print(f"\n{group['candidate_id']} — {group['place']}: {len(group['matched_stops'])} matches")
            for stop in group["matched_stops"]:
                print(f"  {stop['stop_key']} | {stop['name']} | "
                      f"lat={stop['latitude']:.7f}, lon={stop['longitude']:.7f} | "
                      f"type={stop['location_type']} | parent={stop['parent_station']}")
        print("\nThese are GTFS stops/platforms, NOT verified public entrances or homes.")
        print("Project files written: 0 | Journeys computed: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
