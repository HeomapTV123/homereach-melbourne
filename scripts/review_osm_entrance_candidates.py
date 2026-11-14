"""Read OSM-tagged candidate entrances near pinned GTFS station *reference* points.

This is a discovery aid, not an entrance or walking-connectivity validator.
Run after `osmium tags-filter` and `osmium export` as documented.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


STATION_FILE = Path("config/routing_station_references.json")
DEFAULT_FEATURES = Path("data/interim/routing/osm_entrance_candidates.geojsonseq")


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.asin(min(1, math.sqrt(a)))


def load_features(path: Path):
    """Read RFC 8142 record-separated GeoJSON objects; skip malformed records."""
    with path.open("r", encoding="utf-8-sig") as source:
        for line in source:
            line = line.lstrip("\x1e").strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("type") != "Feature":
                continue
            geom = item.get("geometry") or {}
            if geom.get("type") != "Point":
                continue
            xy = geom.get("coordinates")
            if not isinstance(xy, list) or len(xy) < 2:
                continue
            lon, lat = xy[:2]
            if type(lon) not in (int, float) or type(lat) not in (int, float):
                continue
            if not math.isfinite(lon) or not math.isfinite(lat) or not (-180 <= lon <= 180 and -90 <= lat <= 90):
                continue
            props = item.get("properties") or {}
            if not isinstance(props, dict):
                continue
            # Only entry-related features: station-nearby building doors are review candidates too.
            if not (props.get("entrance") or props.get("railway") == "subway_entrance" or props.get("public_transport") == "entrance"):
                continue
            yield {"longitude": lon, "latitude": lat, "properties": props}


def nearest_candidates(stations: list[dict], features: list[dict], radius_m: float = 450, limit: int = 12) -> dict[str, list[dict]]:
    results = {}
    for station in stations:
        hits = []
        for feature in features:
            d = haversine_m(station["latitude"], station["longitude"], feature["latitude"], feature["longitude"])
            if d <= radius_m:
                props = feature["properties"]
                hits.append({
                    "distance_m": round(d),
                    "osm_id": str(props.get("@id", "?")),
                    "osm_type": str(props.get("@type", "?")),
                    "latitude": feature["latitude"], "longitude": feature["longitude"],
                    "entrance": str(props.get("entrance", "")),
                    "railway": str(props.get("railway", "")),
                    "public_transport": str(props.get("public_transport", "")),
                    "name": str(props.get("name", "")),
                    "access": str(props.get("access", "")),
                    "wheelchair": str(props.get("wheelchair", "")),
                })
        hits.sort(key=lambda x: (x["distance_m"], x["osm_id"]))
        results[station["id"]] = hits[:limit]
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES)
    parser.add_argument("--stations", type=Path, default=STATION_FILE)
    parser.add_argument("--radius-m", type=float, default=450)
    args = parser.parse_args()
    if not (0 < args.radius_m <= 1000) or not math.isfinite(args.radius_m):
        parser.error("--radius-m must be between 0 and 1000")
    if not args.features.is_file() or not args.stations.is_file():
        parser.error("Missing inputs: see docs/commute_osm_entrance_review.md")
    stations = json.loads(args.stations.read_text(encoding="utf-8"))["stations"]
    features = list(load_features(args.features))
    results = nearest_candidates(stations, features, args.radius_m)
    print("OSM ENTRANCE TAG CANDIDATES — HUMAN REVIEW REQUIRED")
    print(f"OSM snapshot 2026-10-01; GTFS station references 2026-10-13; radius {args.radius_m:g}m")
    print(f"Exported tagged point features: {len(features)}")
    for station in stations:
        hits = results[station["id"]]
        print(f"\n{station['id']} — {station['name']}: {len(hits)} nearest candidates (up to 12)")
        for h in hits:
            print(f"  {h['distance_m']}m | {h['osm_type']}:{h['osm_id']} | lat={h['latitude']:.7f}, lon={h['longitude']:.7f} | entrance={h['entrance']} railway={h['railway']} public_transport={h['public_transport']} access={h['access']} name={h['name']}")
        if not hits:
            print("  NO TAGGED NODE FOUND: do not infer absence of a public entrance")
    print("\nNo public entrance certified | No walking connections tested | Journeys computed: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
