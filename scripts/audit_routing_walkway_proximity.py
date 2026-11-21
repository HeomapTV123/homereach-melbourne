"""Read-only, conservative segment proximity audit; NOT a route or connectivity check.

Run from project root using the homereach Python environment. Input is Osmium
GeoJSON text sequences exported from a complete-ways `w/highway` PBF.
"""
from __future__ import annotations

import argparse
import heapq
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EARTH_METRES = 6371008.8
# This is a conservative, *incomplete* screening rule, not a pedestrian router.
REJECT_HIGHWAY = {
    "motorway", "motorway_link", "trunk", "trunk_link", "proposed", "construction",
    "raceway", "bus_guideway", "escape", "services", "platform",
}
REJECT_ACCESS = {"no", "private", "agricultural", "forestry", "delivery", "customers"}
REJECT_FOOT = {"no", "private", "use_sidepath"}


def potentially_walkable(tags: dict) -> bool:
    highway = str(tags.get("highway", "")).casefold()
    if not highway or highway in REJECT_HIGHWAY:
        return False
    if tags.get("area") == "yes" or tags.get("motorroad") == "yes":
        return False
    foot = str(tags.get("foot", "")).casefold()
    if foot in REJECT_FOOT:
        return False
    access = str(tags.get("access", "")).casefold()
    if access in REJECT_ACCESS and foot not in {"yes", "designated", "permissive"}:
        return False
    if highway == "cycleway" and foot not in {"yes", "designated", "permissive"}:
        return False
    return True


def segment_distance_m(latitude: float, longitude: float, a: list, b: list) -> float:
    """Local equirectangular point-to-segment distance, metres (small local distances)."""
    lat0 = math.radians(latitude)
    scale_x = EARTH_METRES * math.cos(lat0) * math.pi / 180.0
    scale_y = EARTH_METRES * math.pi / 180.0
    x1, y1 = (a[0] - longitude) * scale_x, (a[1] - latitude) * scale_y
    x2, y2 = (b[0] - longitude) * scale_x, (b[1] - latitude) * scale_y
    dx, dy = x2 - x1, y2 - y1
    t = max(0.0, min(1.0, -(x1 * dx + y1 * dy) / (dx * dx + dy * dy))) if dx * dx + dy * dy else 0.0
    return math.hypot(x1 + t * dx, y1 + t * dy)


def linestring_distance_m(latitude: float, longitude: float, coordinates: list) -> float:
    if len(coordinates) < 2:
        return math.inf
    return min(segment_distance_m(latitude, longitude, a, b) for a, b in zip(coordinates, coordinates[1:]))


def audit(stream, points: list[dict], radius: float, top_k: int) -> tuple[int, int, dict]:
    results = {p["id"]: [] for p in points}
    total = considered = 0
    for line in stream:
        if not line.strip():
            continue
        feature = json.loads(line.lstrip("\x1e"))
        total += 1
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "LineString" or not potentially_walkable(properties):
            continue
        coords = geometry.get("coordinates") or []
        if len(coords) < 2:
            continue
        considered += 1
        for p in points:
            distance = linestring_distance_m(p["latitude"], p["longitude"], coords)
            if distance <= radius:
                item = {"metres": round(distance, 1), "osm_way": properties.get("@id"),
                        "highway": properties.get("highway"), "foot": properties.get("foot", ""),
                        "access": properties.get("access", ""), "surface": properties.get("surface", ""),
                        "indoor": properties.get("indoor", ""), "layer": properties.get("layer", ""),
                        "bridge": properties.get("bridge", ""), "tunnel": properties.get("tunnel", "")}
                results[p["id"]].append(item)
                # Retain nearest few only; streaming input is not held in memory.
                results[p["id"]].sort(key=lambda x: (x["metres"], str(x["osm_way"])))
                del results[p["id"]][top_k:]
    return total, considered, results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/routing_walkway_review_points.json")
    args = parser.parse_args()
    config_path = ROOT / args.config
    config = json.loads(config_path.read_text(encoding="utf-8"))
    source = ROOT / config["source_file"]
    if not source.is_file():
        parser.error(f"Missing {source}. Export the OSM highway PBF to geojsonseq first.")
    points = config["points"]
    assert len({p["id"] for p in points}) == len(points)
    for point in points:
        assert -90 <= point["latitude"] <= 90 and -180 <= point["longitude"] <= 180
    with source.open(encoding="utf-8-sig") as stream:
        total, considered, results = audit(stream, points, config["radius_metres"], config["top_k"])
    print("OSM WALKWAY PROXIMITY AUDIT — NOT CONNECTIVITY OR ROUTING")
    print(f"Features scanned: {total}; provisionally eligible line features: {considered}")
    for p in points:
        print(f"\n{p['id']} | {p['source']}")
        if not results[p["id"]]:
            print("  No provisionally walkable segments within search radius")
        for item in results[p["id"]]:
            print(f"  {item['metres']:.1f}m | way:{item['osm_way']} | highway={item['highway']} foot={item['foot']} access={item['access']} layer={item['layer']} tunnel={item['tunnel']}")
    print("\nNo public entrances certified | No barriers/turns or network connectedness validated | Journeys computed: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
