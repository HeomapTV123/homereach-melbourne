"""The fixture index adapter validates the graph before replacing its index."""
from collections import namedtuple
from pathlib import Path
from types import SimpleNamespace
import sys
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import routing_smoke_fixture as fixture
import routing_street_index_correction as correction


class Envelope:
    def __init__(self, x0, x1, y0, y1):
        self.bounds = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)


class Candidates(set):
    def contains(self, identifier):
        return identifier in self


class Index:
    def __init__(self):
        self.entries = []

    def insert(self, envelope, identifier):
        self.entries.append((envelope.bounds, identifier))

    def query(self, envelope):
        a, b, c, d = envelope.bounds
        return Candidates(identifier for (x0, x1, y0, y1), identifier in self.entries
                          if x0 <= b and x1 >= a and y0 <= d and y1 >= c)


class VertexStore:
    def __init__(self, coordinates):
        self.coordinates = coordinates

    def getVertexCount(self):
        return len(self.coordinates)

    def getCursor(self, index):
        x, y = self.coordinates[index]
        return SimpleNamespace(getFixedLon=lambda: x, getFixedLat=lambda: y)


class Edge:
    def __init__(self, layer, first, last, link=False):
        self.layer, self.first, self.last = layer, first, last
        self.flags = {"walk": True, "link": link, "linkable": not link}
        self.length = 0 if link else 666797
        self.extra_point = None

    def getFromVertex(self):
        return self.first

    def getToVertex(self):
        return self.last

    def getLengthMm(self):
        return self.length

    def getFlag(self, flag):
        return self.flags[flag]

    def getGeometry(self):
        point = namedtuple("Point", "x y")
        coordinates = [self.layer.vertexStore.coordinates[i] for i in (self.first, self.last)]
        result = [point(x / 1e7, y / 1e7) for x, y in coordinates]
        if self.extra_point:
            result.insert(1, point(*self.extra_point))
        return SimpleNamespace(getCoordinates=lambda: result)

    def getEnvelope(self):
        a, b = (self.layer.vertexStore.coordinates[i] for i in (self.first, self.last))
        return Envelope(a[0], b[0], a[1], b[1])


@pytest.fixture
def network(monkeypatch):
    root = ET.fromstring(fixture.street_xml())
    ids = {node.attrib["id"]: i for i, node in enumerate(root.findall("node"))}
    coordinates = [(correction._fixed(node.attrib["lon"]), correction._fixed(node.attrib["lat"]))
                   for node in root.findall("node")]
    layer = SimpleNamespace(vertexStore=VertexStore(coordinates + [(60_000, 180_000), (300_000, 180_000)]))
    edges = []
    for way in root.findall("way"):
        first, last = (ids[node.attrib["ref"]] for node in way.findall("nd"))
        edges.extend([Edge(layer, first, last), Edge(layer, last, first)])
    for stop, grid in ((49, coordinates.index((60_000, 180_000))),
                       (50, coordinates.index((300_000, 180_000)))):
        edges.extend([Edge(layer, stop, grid, True), Edge(layer, grid, stop, True)])
    layer.edgeStore = SimpleNamespace(nEdges=lambda: len(edges), getCursor=lambda i: edges[i])
    index = Index()
    for i in range(0, 168, 2):
        first, last = (coordinates[v] for v in (edges[i].first, edges[i].last))
        # Reproduce the source sign error before building the corrected index.
        index.insert(Envelope(first[0], 2 * first[0] - last[0], first[1], 2 * first[1] - last[1]), i)
    layer.spatialIndex = index
    native_transit = SimpleNamespace(stopIdForIndex=["synthetic.gtfs:SMOKE_WEST", "synthetic.gtfs:SMOKE_EAST"])
    native_transit.getCoordinateForStopFixed = lambda i: SimpleNamespace(
        getX=lambda: layer.vertexStore.coordinates[49 + i][0],
        getY=lambda: layer.vertexStore.coordinates[49 + i][1])
    transit = SimpleNamespace(_transit_layer=native_transit, get_street_vertex_for_stop=lambda i: 49 + i)
    flags = SimpleNamespace(ALLOWS_PEDESTRIAN="walk", LINK="link", LINKABLE="linkable")
    monkeypatch.setattr(correction, "_runtime_types", lambda: (Index, flags, Envelope))
    return SimpleNamespace(street_layer=SimpleNamespace(_street_layer=layer), transit_layer=transit)


def test_fixed_envelopes_restore_candidate_coverage_without_graph_changes(network):
    layer = network.street_layer._street_layer
    previous = layer.spatialIndex
    with correction.correct_fixture_index(network, fixture) as audit:
        assert layer.spatialIndex is not previous
        assert audit["street_pairs"] == 84
        assert audit["connector_pairs"] == 2
        assert audit["coverage_before"]["missing_edge_candidates"] > 0
        assert audit["coverage_after"] == {"edge_points_checked": 420, "missing_edge_candidates": 0}
        assert audit["applied"] and not audit["restored"]
    assert layer.spatialIndex is previous
    assert audit["restored"] and audit["network_unchanged"]
    assert audit["graph_sha256_after"] == audit["graph_sha256_before"]


def test_restores_index_after_query_exception(network):
    previous = network.street_layer._street_layer.spatialIndex
    with pytest.raises(RuntimeError, match="query failed"):
        with correction.correct_fixture_index(network, fixture) as audit:
            raise RuntimeError("query failed")
    assert network.street_layer._street_layer.spatialIndex is previous
    assert audit["restored"] and audit["network_unchanged"]


def test_nested_context_is_rejected_and_outer_context_restores(network):
    previous = network.street_layer._street_layer.spatialIndex
    with correction.correct_fixture_index(network, fixture) as audit:
        replacement = network.street_layer._street_layer.spatialIndex
        with pytest.raises(ValueError, match="cannot be nested"):
            with correction.correct_fixture_index(network, fixture):
                pytest.fail("nested scope entered")
        assert network.street_layer._street_layer.spatialIndex is replacement
    assert network.street_layer._street_layer.spatialIndex is previous
    assert audit["restored"]


def test_changed_xml_is_refused_before_native_loading(monkeypatch):
    changed = SimpleNamespace(street_xml=lambda: fixture.street_xml().replace(b"residential", b"footway"))
    monkeypatch.setattr(correction, "_runtime_types", lambda: pytest.fail("native imports attempted"))
    with pytest.raises(ValueError, match="reviewed fixture XML"):
        with correction.correct_fixture_index(None, changed):
            pytest.fail("scope entered")


def test_changed_stop_coordinates_are_refused(network):
    tables = fixture.gtfs_tables()
    tables["stops.txt"] = tables["stops.txt"].replace(b"0.0300000", b"0.0301000")
    changed = SimpleNamespace(street_xml=fixture.street_xml, gtfs_tables=lambda: tables)
    with pytest.raises(ValueError, match="reviewed graph and stop coordinates"):
        with correction.correct_fixture_index(network, changed):
            pytest.fail("scope entered")


@pytest.mark.parametrize("change", ["vertex", "stop_link", "walk", "length", "shape", "link", "extra_stop", "pair"])
def test_unreviewed_graph_is_refused_without_replacing_index(network, change):
    layer = network.street_layer._street_layer
    previous = layer.spatialIndex
    edge = layer.edgeStore.getCursor(0)
    if change == "vertex":
        layer.vertexStore.coordinates[0] = (1, 1)
    elif change == "stop_link":
        network.transit_layer.get_street_vertex_for_stop = lambda i: 50 - i
    elif change == "walk":
        edge.flags["walk"] = False
    elif change == "length":
        edge.length += 1
    elif change == "shape":
        edge.extra_point = (.001, .001)
    elif change == "link":
        edge.flags["link"] = True
    elif change == "extra_stop":
        network.transit_layer._transit_layer.stopIdForIndex.append("unexpected")
    elif change == "pair":
        edge.first = 2
    with pytest.raises(ValueError):
        with correction.correct_fixture_index(network, fixture):
            pytest.fail("scope entered")
    assert layer.spatialIndex is previous


def test_graph_mutation_is_reported_after_index_restoration(network):
    layer = network.street_layer._street_layer
    previous = layer.spatialIndex
    with pytest.raises(ValueError, match="graph changed"):
        with correction.correct_fixture_index(network, fixture) as audit:
            layer.edgeStore.getCursor(0).length += 1
            layer.edgeStore.getCursor(1).length += 1
    assert layer.spatialIndex is previous
    assert audit["restored"] and not audit["network_unchanged"]
