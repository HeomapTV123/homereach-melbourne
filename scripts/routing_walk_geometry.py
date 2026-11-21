"""Independent geometry checks for the fixed fictional walking fixture.

This module uses only the standard library. It proves a direct walking path
from the committed XML, then compares raw returned lines and reported lengths
with that path. It never clips, reverses, repairs or drops returned geometry.
The spherical metric and explicit tolerances are fixture diagnostics, not a
general street-network router or a claim of real-world route accuracy.
"""
from __future__ import annotations

import csv
import hashlib
from io import StringIO
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import routing_smoke_fixture as fixture


REFERENCE_XML = Path(__file__).resolve().parents[1] / "tests/fixtures/routing_smoke/streets.osm"
EXPECTED_CRS = "EPSG:4326"
EARTH_RADIUS_M = 6_371_000.0
ENDPOINT_TOLERANCE_M = 2.0
ABSOLUTE_LENGTH_TOLERANCE_M = 2.0
RELATIVE_LENGTH_TOLERANCE = 0.002


def _finite(value) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _point(value) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2 or not all(_finite(v) for v in value):
        raise ValueError("Expected a finite longitude/latitude coordinate pair.")
    lon, lat = value
    if not -180 <= lon <= 180 or not -90 <= lat <= 90:
        raise ValueError("Coordinate lies outside longitude/latitude bounds.")
    return float(lon), float(lat)


def haversine_m(first, second) -> float:
    """Spherical separation in metres; input order is longitude, latitude."""
    lon1, lat1 = map(math.radians, first)
    lon2, lat2 = map(math.radians, second)
    value = (math.sin((lat2 - lat1) / 2) ** 2
             + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(max(0.0, value))))


def _length(points) -> float:
    return sum(haversine_m(a, b) for a, b in zip(points, points[1:]))


def _reference_path(root, nodes, start, end) -> list[tuple[float, float]]:
    """Prove coverage by unrestricted bidirectional ways on this exact row."""
    start, end = _point(start), _point(end)
    if start[1] != end[1] or start == end:
        raise ValueError("The fixed oracle requires distinct endpoints on the same grid row.")
    low, high = sorted((start[0], end[0]))
    intervals = []
    for way in root.findall("way"):
        references = [int(node.attrib["ref"]) for node in way.findall("nd")]
        if len(references) != 2 or any(identifier not in nodes for identifier in references):
            raise ValueError("Reference XML contains an incomplete grid edge.")
        first, second = (nodes[identifier] for identifier in references)
        if first[1] != start[1] or second[1] != start[1]:
            continue
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in way.findall("tag")}
        if any(tags.get(key) != expected for key, expected in
               (("highway", "residential"), ("foot", "yes"), ("oneway", "no"))):
            raise ValueError("Reference row does not have the reviewed walking permissions.")
        intervals.append(tuple(sorted((first[0], second[0]))))
    covered = low
    for left, right in sorted(intervals):
        if right < covered:
            continue
        if left > covered + 1e-12:
            break
        covered = max(covered, right)
        if covered >= high:
            break
    if covered < high:
        raise ValueError("Reference XML does not contain a continuous direct walking path.")
    interior = sorted({point[0] for point in nodes.values()
                       if point[1] == start[1] and low < point[0] < high},
                      reverse=start[0] > end[0])
    return [start, *((lon, start[1]) for lon in interior), end]


def reference_walks() -> tuple[dict, str]:
    """Read the fixed XML and GTFS coordinates, refusing changed XML evidence."""
    text = REFERENCE_XML.read_text(encoding="utf-8")
    if text != fixture.street_xml().decode("utf-8"):
        raise ValueError("Committed reference XML differs from the reviewed fixture generator.")
    root = ET.fromstring(text)
    nodes = {int(node.attrib["id"]): _point((float(node.attrib["lon"]), float(node.attrib["lat"])))
             for node in root.findall("node")}
    stops = {row["stop_id"]: _point((float(row["stop_lon"]), float(row["stop_lat"])))
             for row in csv.DictReader(StringIO(fixture.gtfs_tables()["stops.txt"].decode("utf-8")))}
    pairs = {"direct": (fixture.ORIGIN, fixture.DESTINATION),
             "access": (fixture.ORIGIN, stops[fixture.START_STOP_ID]),
             "egress": (stops[fixture.END_STOP_ID], fixture.DESTINATION)}
    result = {}
    for role, (start, end) in pairs.items():
        path = _reference_path(root, nodes, start, end)
        distance = _length(path)
        result[role] = {"start": list(start), "end": list(end), "path": [list(p) for p in path],
                        "distance_m": distance,
                        "length_tolerance_m": max(ABSOLUTE_LENGTH_TOLERANCE_M,
                                                   RELATIVE_LENGTH_TOLERANCE * distance)}
    return result, hashlib.sha256(text.encode("utf-8")).hexdigest()


def _observe_walk(row: dict, query: str, role: str, reference: dict, result: dict) -> None:
    counts = result["counts"]
    counts["walking_legs_checked"] += 1
    observation = {"query": query, "role": role, "option": row.get("option"),
                   "segment": row.get("segment"), "expected_start": reference["start"],
                   "expected_end": reference["end"], "reference_distance_m": reference["distance_m"],
                   "length_tolerance_m": reference["length_tolerance_m"], "problems": []}
    result["observations"].append(observation)

    def failure(counter, message):
        counts[counter] += 1
        observation["problems"].append(message)
        result["problems"].append(f"{query} option {row.get('option')} segment {row.get('segment')}: {message}")

    distance = row.get("distance_m")
    distance_valid = _finite(distance) and distance > 0
    observation["reported_distance_m"] = distance if distance_valid else None
    if not distance_valid:
        failure("malformed_rows", "Reported walking distance must be positive and finite.")
    geometry = row.get("geometry")
    try:
        if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
            raise ValueError("Expected one continuous LineString geometry.")
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
            raise ValueError("Walking geometry requires at least two coordinate pairs.")
        points = [_point(coordinate) for coordinate in coordinates]
        geometry_length = _length(points)
        if geometry_length <= 0:
            raise ValueError("Walking geometry has zero length.")
    except (ValueError, TypeError, OverflowError) as error:
        failure("malformed_geometries", str(error))
        return

    start, end = reference["start"], reference["end"]
    forward = max(haversine_m(points[0], start), haversine_m(points[-1], end))
    reverse = max(haversine_m(points[0], end), haversine_m(points[-1], start))
    error = min(forward, reverse)
    orientation = "forward" if forward <= reverse else "reverse"
    if error > ENDPOINT_TOLERANCE_M:
        orientation = "unmatched"
        failure("endpoint_mismatches", "Geometry endpoints do not match this walk's required endpoints.")
    low, high = sorted((start[0], end[0]))
    off_path = max(haversine_m(point, (min(high, max(low, point[0])), start[1])) for point in points)
    if off_path > ENDPOINT_TOLERANCE_M:
        failure("off_reference_path", "Geometry extends outside the direct reference walking path.")
    observation.update(first_coordinate=list(points[0]), last_coordinate=list(points[-1]),
                       geometry_length_m=geometry_length, forward_endpoint_error_m=forward,
                       reverse_endpoint_error_m=reverse, orientation=orientation,
                       endpoint_error_m=error, max_off_reference_path_m=off_path)
    if distance_valid:
        geometry_error = abs(geometry_length - distance)
        shortest_error = abs(distance - reference["distance_m"])
        observation.update(geometry_reported_error_m=geometry_error,
                           reported_shortest_error_m=shortest_error)
        if geometry_error > reference["length_tolerance_m"]:
            failure("geometry_distance_mismatches", "Geometry length disagrees with the reported walking distance.")
        if shortest_error > reference["length_tolerance_m"]:
            failure("shortest_distance_mismatches", "Reported distance disagrees with the independently proved direct path.")


def audit_walk_geometry(report: dict) -> dict:
    """Audit every returned walk without altering raw rows or requiring a JVM."""
    result = {
        "status": "failed", "crs_expected": EXPECTED_CRS,
        "tolerance_policy": {"earth_radius_m": EARTH_RADIUS_M,
                             "endpoint_tolerance_m": ENDPOINT_TOLERANCE_M,
                             "absolute_length_tolerance_m": ABSOLUTE_LENGTH_TOLERANCE_M,
                             "relative_length_tolerance": RELATIVE_LENGTH_TOLERANCE,
                             "length_rule": "max(absolute tolerance, relative tolerance * reference distance)",
                             "orientation": "Either direction is accepted; observed orientation is recorded."},
        "reference_walks": {},
        "counts": {name: 0 for name in ("walking_legs_checked", "endpoint_mismatches",
                   "geometry_distance_mismatches", "shortest_distance_mismatches", "off_reference_path",
                   "malformed_rows", "malformed_geometries", "incomplete_options", "unsupported_crs")},
        "observations": [], "problems": [],
    }
    try:
        result["reference_walks"], result["reference_xml_sha256"] = reference_walks()
    except (OSError, KeyError, ValueError, ET.ParseError) as error:
        result["problems"].append(f"Cannot establish the fixed walking reference: {error}")
        return result
    if not isinstance(report, dict):
        result["problems"].append("Walking geometry report must be an object.")
        return result
    crs = report.get("geometry_crs")
    for query in ("walking", "transit"):
        if not isinstance(crs, dict) or crs.get(query) != EXPECTED_CRS:
            result["counts"]["unsupported_crs"] += 1
            result["problems"].append(f"{query}: explicit EPSG:4326 geometry CRS is required.")
            continue
        rows = report.get(query)
        if not isinstance(rows, list) or not rows:
            result["counts"]["incomplete_options"] += 1
            result["problems"].append(f"{query}: no returned legs are available for the geometry check.")
            continue
        groups = {}
        for row in rows:
            if not isinstance(row, dict) or type(row.get("option")) is not int or type(row.get("segment")) is not int:
                result["counts"]["malformed_rows"] += 1
                result["problems"].append(f"{query}: malformed option or segment identifier.")
                continue
            groups.setdefault(row["option"], []).append((row["segment"], row.get("mode")))
            if row.get("mode") != "WALK":
                continue
            role = "direct" if query == "walking" and row["segment"] == 0 else None
            if query == "transit":
                role = {0: "access", 2: "egress"}.get(row["segment"])
            if role is None:
                result["counts"]["malformed_rows"] += 1
                result["problems"].append(f"{query}: walking leg has an unexpected segment number.")
                continue
            _observe_walk(row, query, role, result["reference_walks"][role], result)
        expected = [(0, "WALK")] if query == "walking" else [(0, "WALK"), (1, "BUS"), (2, "WALK")]
        for option, sequence in groups.items():
            if sorted(sequence, key=lambda item: item[0]) != expected:
                result["counts"]["incomplete_options"] += 1
                result["problems"].append(f"{query} option {option}: incomplete or unexpected leg sequence.")
    result["status"] = "failed" if result["problems"] else "passed"
    return result
