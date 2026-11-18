"""Correct the derived R5 spatial index for the reviewed tiny fixture only.

The pinned IntHashGrid LineString insertion reflects segments about their
first coordinate. Its fixed-coordinate Envelope overload works correctly.
This context builds a replacement index through that overload, after checking
the full fixture graph and its existing stop links. It changes no vertices,
edges, permissions or costs and restores the previous index on exit.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import csv
from decimal import Decimal
import hashlib
from io import StringIO
import json
from pathlib import Path
import xml.etree.ElementTree as ET


ADAPTER_NAME = "homereach_fixed_fixture_spatial_index"
ADAPTER_VERSION = 1
ENGINE_SHA256 = "d50be106cadd7b636cfc0e209052767d7df570629f79fdf98ecd5cf5d2d89be7"
FIXTURE_XML_SHA256 = "d6244955cb3a5e85fce78833749350bce47cf657b963374c74eb23ab78c64f3c"
FIXED_FACTOR = 10_000_000
_active = False


def _fixed(value) -> int:
    return int(Decimal(str(value)) * FIXED_FACTOR)


def _fixture_reference(fixture) -> dict:
    xml = fixture.street_xml().replace(b"\r\n", b"\n")
    if hashlib.sha256(xml).hexdigest() != FIXTURE_XML_SHA256:
        raise ValueError("Spatial index correction requires the reviewed fixture XML.")
    root = ET.fromstring(xml)
    nodes = {node.attrib["id"]: (_fixed(node.attrib["lon"]), _fixed(node.attrib["lat"]))
             for node in root.findall("node")}
    edges = Counter()
    for way in root.findall("way"):
        ends = [nodes[node.attrib["ref"]] for node in way.findall("nd")]
        edges[tuple(sorted(ends))] += 1
    stops = {row["stop_id"]: (_fixed(row["stop_lon"]), _fixed(row["stop_lat"]))
             for row in csv.DictReader(StringIO(fixture.gtfs_tables()["stops.txt"].decode("utf-8")))}
    expected_stops = {"SMOKE_WEST": (60_000, 180_000), "SMOKE_EAST": (300_000, 180_000)}
    if len(nodes) != 49 or sum(edges.values()) != 84 or stops != expected_stops:
        raise ValueError("Spatial index correction requires the reviewed graph and stop coordinates.")
    return {"nodes": nodes, "edges": edges, "stops": stops}


def _runtime_types():
    # Native imports happen only in the explicit, already-started worker.
    from com.conveyal.r5.streets import EdgeStore, IntHashGrid
    from java.io import File
    from org.locationtech.jts.geom import Envelope

    source = Path(str(File(IntHashGrid.class_.getProtectionDomain().getCodeSource().getLocation().toURI()).getPath()))
    with source.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if digest != ENGINE_SHA256:
        raise ValueError("Spatial index correction requires the reviewed R5 JAR.")
    return IntHashGrid, EdgeStore.EdgeFlag, Envelope


def _vertex(layer, index) -> tuple[int, int]:
    vertex = layer.vertexStore.getCursor(index)
    return int(vertex.getFixedLon()), int(vertex.getFixedLat())


def _inspect_graph(network, reference, flags) -> dict:
    layer = network.street_layer._street_layer
    transit = network.transit_layer
    if int(layer.vertexStore.getVertexCount()) != 51 or int(layer.edgeStore.nEdges()) != 172:
        raise ValueError("Spatial index correction is confined to the 51-vertex, 172-directed-edge fixture network.")
    stop_ids = list(transit._transit_layer.stopIdForIndex)
    if len(stop_ids) != 2:
        raise ValueError("The fixture must have exactly two transit stops.")
    linked_stops = {}
    for index, scoped_id in enumerate(stop_ids):
        identifier = str(scoped_id).rsplit(":", 1)[-1]
        if identifier not in reference["stops"] or identifier in linked_stops:
            raise ValueError("Unexpected or duplicate fixture stop ID.")
        vertex_id = int(transit.get_street_vertex_for_stop(index))
        expected = reference["stops"][identifier]
        coordinate = transit._transit_layer.getCoordinateForStopFixed(index)
        if (_vertex(layer, vertex_id) != expected
                or (int(coordinate.getX()), int(coordinate.getY())) != expected):
            raise ValueError("An existing transit stop is linked at the wrong coordinate; index repair cannot fix its linkage.")
        linked_stops[identifier] = vertex_id
    if len(set(linked_stops.values())) != 2:
        raise ValueError("The fixture stops require distinct street vertices.")
    coordinates = [_vertex(layer, index) for index in range(51)]
    expected_coordinates = Counter(reference["nodes"].values()) + Counter(reference["stops"].values())
    if Counter(coordinates) != expected_coordinates:
        raise ValueError("Loaded graph vertices do not match the fixed fixture.")

    street_edges, connectors, inventory = [], [], []
    actual_edges = Counter()
    for index in range(0, 172, 2):
        edge = layer.edgeStore.getCursor(index)
        reverse = layer.edgeStore.getCursor(index + 1)
        first, last = int(edge.getFromVertex()), int(edge.getToVertex())
        if int(reverse.getFromVertex()) != last or int(reverse.getToVertex()) != first:
            raise ValueError("Fixture directed-edge pair has inconsistent endpoints.")
        ends = (coordinates[first], coordinates[last])
        shape = edge.getGeometry()
        geometry = [(_fixed(point.x), _fixed(point.y)) for point in shape.getCoordinates()]
        if geometry != list(ends):
            raise ValueError("Fixture edge geometry differs from its two reviewed endpoint vertices.")
        walk_flags = [bool(e.getFlag(flags.ALLOWS_PEDESTRIAN)) for e in (edge, reverse)]
        link_flags = [bool(e.getFlag(flags.LINK)) for e in (edge, reverse)]
        linkable_flags = [bool(e.getFlag(flags.LINKABLE)) for e in (edge, reverse)]
        length = int(edge.getLengthMm())
        if not all(walk_flags) or int(reverse.getLengthMm()) != length:
            raise ValueError("Fixture edge permissions or paired lengths differ from the reviewed input.")
        if all(link_flags):
            if length != 0 or ends[0] != ends[1] or any(linkable_flags):
                raise ValueError("Only the reviewed zero-length, nonlinkable transit connectors are supported.")
            stop_ends = {first, last}.intersection(linked_stops.values())
            if len(stop_ends) != 1:
                raise ValueError("Transit connector must join exactly one stop vertex to its matching grid vertex.")
            connectors.append(next(iter(stop_ends)))
        elif not any(link_flags) and all(linkable_flags) and length > 0:
            if {first, last}.intersection(linked_stops.values()):
                raise ValueError("A stop vertex cannot replace a reviewed grid endpoint.")
            actual_edges[tuple(sorted(ends))] += 1
            street_edges.append((index, ends))
        else:
            raise ValueError("Unexpected linkability or connector flag combination.")
        inventory.append([index, first, last, length, walk_flags, link_flags, linkable_flags, geometry])
    if actual_edges != reference["edges"] or sorted(connectors) != sorted(linked_stops.values()):
        raise ValueError("Loaded streets or transit connectors do not match the fixed fixture.")
    fingerprint = hashlib.sha256(json.dumps({"vertices": coordinates, "edges": inventory,
                                            "linked_stops": linked_stops}, sort_keys=True).encode()).hexdigest()
    return {"street_edges": street_edges, "fingerprint": fingerprint,
            "linked_stop_vertices": linked_stops, "street_pairs": len(street_edges),
            "connector_pairs": len(connectors)}


def _coverage(index, edges, envelope_type) -> dict:
    checked, missing = 0, 0
    for identifier, (first, last) in edges:
        for numerator in range(5):
            x = first[0] + (last[0] - first[0]) * numerator / 4
            y = first[1] + (last[1] - first[1]) * numerator / 4
            candidates = index.query(envelope_type(x, x, y, y))
            checked += 1
            if not candidates.contains(identifier):
                missing += 1
    return {"edge_points_checked": checked, "missing_edge_candidates": missing}


@contextmanager
def correct_fixture_index(network, fixture):
    """Replace only the derived index during this fixed-fixture worker scope."""
    global _active
    if _active:
        raise ValueError("The fixed-fixture index correction cannot be nested.")
    reference = _fixture_reference(fixture)
    index_type, flags, envelope_type = _runtime_types()
    graph = _inspect_graph(network, reference, flags)
    layer = network.street_layer._street_layer
    original = layer.spatialIndex
    rebuilt = index_type()
    for identifier, _ in graph["street_edges"]:
        rebuilt.insert(layer.edgeStore.getCursor(identifier).getEnvelope(), identifier)
    coverage_before = _coverage(original, graph["street_edges"], envelope_type)
    coverage_after = _coverage(rebuilt, graph["street_edges"], envelope_type)
    if coverage_after["missing_edge_candidates"]:
        raise ValueError("Rebuilt spatial index still omits a reviewed street segment.")
    audit = {"name": ADAPTER_NAME, "version": ADAPTER_VERSION,
             "source_sha256": hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
             "engine_sha256": ENGINE_SHA256, "fixture_xml_sha256": FIXTURE_XML_SHA256,
             "graph_sha256_before": graph["fingerprint"], "graph_sha256_after": None,
             "street_pairs": graph["street_pairs"], "connector_pairs": graph["connector_pairs"],
             "linked_stop_vertices": graph["linked_stop_vertices"],
             "coverage_before": coverage_before, "coverage_after": coverage_after,
             "applied": False, "restored": False, "network_unchanged": False}
    _active = True
    try:
        layer.spatialIndex = rebuilt
        audit["applied"] = True
        yield audit
    finally:
        layer.spatialIndex = original
        audit["restored"] = True
        _active = False
        after = _inspect_graph(network, reference, flags)
        audit["graph_sha256_after"] = after["fingerprint"]
        audit["network_unchanged"] = after["fingerprint"] == graph["fingerprint"]
        if not audit["network_unchanged"]:
            raise ValueError("The fixture graph changed while its spatial index correction was active.")
