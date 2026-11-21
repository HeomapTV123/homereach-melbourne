"""Native path construction preserves selected edges, splits and costs."""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/routing_street_geometry_correction.py"
SPEC = importlib.util.spec_from_file_location("street_geometry_under_test", SCRIPT)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def edge_pair(identifier, start, end, coordinates):
    return {identifier: {"from_vertex": start, "to_vertex": end, "coordinates": coordinates},
            identifier + 1: {"from_vertex": end, "to_vertex": start, "coordinates": list(reversed(coordinates))}}


def split(edge, first, last, segment, fraction, point):
    return {"edge": edge, "vertex0": first, "vertex1": last,
            "segment": segment, "fraction": fraction, "point": point}


@pytest.fixture
def curved_path():
    edges = edge_pair(0, 0, 1, [(0, 0), (1, 1), (2, 0)])
    edges.update(edge_pair(2, 1, 2, [(2, 0), (2.1, 1), (2, 2)]))
    edges.update(edge_pair(4, 2, 3, [(2, 2), (3, 3), (4, 2)]))
    return {"states": [{"vertex": 1, "back_edge": 0}, {"vertex": 2, "back_edge": 2},
                       {"vertex": -1, "back_edge": 4}],
            "edges": edges, "origin": (.25, .3),
            "origin_split": split(0, 0, 1, 0, .25, (.25, .25)),
            "destination": (3.5, 2.6),
            "destination_split": split(4, 2, 3, 1, .5, (3.5, 2.5))}


def test_curved_native_path_retains_intermediate_vertices_and_explicit_connectors(curved_path):
    before = deepcopy(curved_path)
    coordinates = m.build_path_coordinates(**curved_path)
    assert coordinates == [(.25, .3), (.25, .25), (1, 1), (2, 0), (2.1, 1),
                           (2, 2), (3, 3), (3.5, 2.5), (3.5, 2.6)]
    assert curved_path == before


def test_reverse_search_is_built_from_the_same_directed_native_edges(curved_path):
    reversed_case = deepcopy(curved_path)
    reversed_case.update(origin=curved_path["destination"], destination=curved_path["origin"],
                         origin_split=curved_path["destination_split"],
                         destination_split=curved_path["origin_split"], reverse=True,
                         states=[{"vertex": 2, "back_edge": 4}, {"vertex": 1, "back_edge": 2},
                                 {"vertex": -1, "back_edge": 0}])
    assert m.build_path_coordinates(**reversed_case) == m.build_path_coordinates(**curved_path)


def test_access_uses_partial_initial_edge_and_retains_zero_length_stop_link():
    edges = edge_pair(0, 0, 1, [(.006, .018), (.012, .018)])
    edges.update(edge_pair(2, 0, 99, [(.006, .018), (.006, .018)]))
    coordinates = m.build_path_coordinates(
        [{"vertex": 0, "back_edge": 1}, {"vertex": 99, "back_edge": 2}], edges,
        origin=(.0061, .018), origin_split=split(0, 0, 1, 0, 1 / 60, (.0061, .018)))
    assert coordinates == [(.0061, .018), (.006, .018)]


def test_egress_retains_selected_stop_and_true_destination_in_traveller_order():
    edges = edge_pair(14, 10, 11, [(.024, .018), (.030, .018)])
    edges.update(edge_pair(16, 99, 11, [(.030, .018), (.030, .018)]))
    coordinates = m.build_path_coordinates(
        [{"vertex": 11, "back_edge": 15}, {"vertex": 99, "back_edge": 16}], edges,
        origin=(.0299, .018), origin_split=split(14, 10, 11, 0, 59 / 60, (.0299, .018)), reverse=True)
    assert coordinates == [(.030, .018), (.0299, .018)]


@pytest.mark.parametrize("at_last,reverse", [(False, False), (True, False), (False, True), (True, True)])
def test_initial_partial_edge_supports_each_endpoint_and_search_direction(at_last, reverse):
    edges = edge_pair(0, 0, 1, [(0, 0), (1, 1), (2, 0)])
    vertex = int(at_last)
    back_edge = int((not at_last) != reverse)
    result = m.build_path_coordinates([{"vertex": vertex, "back_edge": back_edge}], edges,
                                     origin=(.5, .5), origin_split=split(0, 0, 1, 0, .5, (.5, .5)),
                                     reverse=reverse)
    expected = [(.5, .5), (1, 1), (2, 0)] if at_last else [(.5, .5), (0, 0)]
    assert result == (list(reversed(expected)) if reverse else expected)


def test_legitimate_zero_length_result_has_a_valid_repeated_coordinate():
    edges = edge_pair(0, 0, 1, [(0, 0), (1, 0)])
    result = m.build_path_coordinates([{"vertex": 0, "back_edge": 1}], edges,
                                     origin=(0, 0), origin_split=split(0, 0, 1, 0, 0, (0, 0)))
    assert result == [(0, 0), (0, 0)]


@pytest.mark.parametrize("change,match", [
    (lambda p: p["origin_split"].update(segment=20), "segment"),
    (lambda p: p["origin_split"].update(fraction=float("nan")), "fraction"),
    (lambda p: p["origin_split"].update(fraction=True), "fraction"),
    (lambda p: p["origin_split"].update(point=(.9, .9)), "coordinate disagrees"),
    (lambda p: p["origin_split"].update(edge=1), "forward edge"),
    (lambda p: p["origin_split"].update(vertex1=99), "actual vertices"),
    (lambda p: p["states"][0].update(vertex=99), "Initial state"),
    (lambda p: p["states"][0].update(back_edge=1), "Initial state back-edge"),
    (lambda p: p["states"][1].update(back_edge=3), "adjacent state vertices"),
    (lambda p: p["states"][-1].update(back_edge=5), "Destination back-edge"),
    (lambda p: p["states"][-1].update(vertex=-3), "Unsupported native terminal"),
    (lambda p: p["edges"][2].update(coordinates=[(7, 0), (2, 2)]), "disconnected"),
    (lambda p: p["edges"][2].update(coordinates=[(2, 0), (float("inf"), 2)]), "finite"),
    (lambda p: p.update(destination=None), "supplied together"),
    (lambda p: p.update(reverse=1), "direction"),
    (lambda p: p.update(states=[]), "nonempty"),
])
def test_rejects_unverified_or_inconsistent_native_path(curved_path, change, match):
    change(curved_path)
    with pytest.raises(ValueError, match=match):
        m.build_path_coordinates(**curved_path)


def test_does_not_hide_a_route_detour_with_a_direct_requested_line():
    edges = edge_pair(0, 0, 1, [(0, 0), (1, 0)])
    path = m.build_path_coordinates(
        [{"vertex": 1, "back_edge": 0}, {"vertex": -1, "back_edge": 1}], edges,
        origin=(.2, 0), origin_split=split(0, 0, 1, 0, .2, (.2, 0)),
        destination=(.4, 0), destination_split=split(0, 0, 1, 0, .4, (.4, 0)))
    assert path == [(.2, 0), (1, 0), (.4, 0)]


def test_native_bridge_preserves_terminal_costs_and_actual_splits(curved_path, monkeypatch):
    class State:
        def __init__(self, row, back):
            self.vertex, self.backEdge = row["vertex"], row["back_edge"]
            self.backState, self.distance = back, 987654321
        def getDurationSeconds(self):
            return 321
    def native_split(value):
        return SimpleNamespace(edge=value["edge"], vertex0=value["vertex0"], vertex1=value["vertex1"],
                               seg=value["segment"], frac=value["fraction"],
                               fixedLon=round(value["point"][0] * 10_000_000),
                               fixedLat=round(value["point"][1] * 10_000_000), distanceToEdge_mm=0)
    def cursor(identifier):
        edge = curved_path["edges"][identifier]
        coordinates = [SimpleNamespace(x=x, y=y) for x, y in edge["coordinates"]]
        return SimpleNamespace(getFromVertex=lambda: edge["from_vertex"],
                               getToVertex=lambda: edge["to_vertex"],
                               getGeometry=lambda: SimpleNamespace(getCoordinates=lambda: coordinates))
    state = None
    for row in curved_path["states"]:
        state = State(row, state)
    router = SimpleNamespace(profileRequest=SimpleNamespace(reverseSearch=False),
                             streetLayer=SimpleNamespace(edgeStore=SimpleNamespace(getCursor=cursor)),
                             getOriginSplit=lambda: native_split(curved_path["origin_split"]),
                             getDestinationSplit=lambda: native_split(curved_path["destination_split"]))
    monkeypatch.setitem(sys.modules, "shapely", SimpleNamespace(LineString=lambda coords: coords))
    on_street_destination = curved_path["destination_split"]["point"]
    context = {"router": router, "origin_lon_lat": curved_path["origin"],
               "destination_lon_lat": on_street_destination, "reverse": False}
    segment = m.street_segment_from_context(state, context)
    assert segment.distance == 987654321
    assert segment.duration == 321
    expected = dict(curved_path, destination=on_street_destination)
    assert segment.geometry == m.build_path_coordinates(**expected)
    off_street_split = native_split(curved_path["destination_split"])
    off_street_split.distanceToEdge_mm = 11_100
    router.getDestinationSplit = lambda: off_street_split
    with pytest.raises(ValueError, match="connector cost"):
        m.street_segment_from_context(state, context)
    state.backState = state
    with pytest.raises(ValueError, match="Cyclic"):
        m.street_segment_from_context(state, context)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    package = tmp_path / "r5py"
    source = package / "r5/trip_planner.py"
    source.parent.mkdir(parents=True)
    text = "class TripPlanner:\n    def _street_segment_from_router_state(self, state, mode):\n        return ('upstream', state, mode)\n"
    source.write_text(text)
    module = ModuleType("r5py.r5.trip_planner")
    module.__file__ = str(source)
    exec(compile(text, str(source), "exec"), module.__dict__)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(m, "SOURCE_SHA256", {"r5/trip_planner.py": hashlib.sha256(text.encode()).hexdigest()})
    native = ModuleType("routing_street_origin_correction")
    native.context_for_state = lambda state: {"test_state": state}
    monkeypatch.setitem(sys.modules, native.__name__, native)
    r5py = SimpleNamespace(__version__="1.1.7", __file__=str(package / "__init__.py"),
                          DetailedItineraries=SimpleNamespace(NUM_THREADS=1))
    return r5py, module, native, source


def test_scoped_construction_uses_bound_native_context_and_restores(runtime, monkeypatch):
    r5py, module, _, _ = runtime
    original = module.TripPlanner._street_segment_from_router_state
    mode = SimpleNamespace(name="WALK")
    observed = []
    def build(state, context):
        observed.append((state, context))
        return SimpleNamespace(distance=123, duration=456, geometry="native selected geometry")
    monkeypatch.setattr(m, "street_segment_from_context", build)
    with m.correct_street_geometries(r5py) as audit:
        result = module.TripPlanner()._street_segment_from_router_state("state", mode)
        assert result.distance == 123 and result.duration == 456
        assert observed == [("state", {"test_state": "state"})]
        assert audit["applied"] and not audit["restored"]
    assert audit["segments_constructed"] == 1 and audit["native_costs_preserved"]
    assert audit["restored"] and module.TripPlanner._street_segment_from_router_state is original


@pytest.mark.parametrize("cause", ["context", "mode", "builder"])
def test_scope_restores_after_unsupported_or_failed_construction(runtime, monkeypatch, cause):
    r5py, module, native, _ = runtime
    original = module.TripPlanner._street_segment_from_router_state
    if cause == "context":
        native.context_for_state = lambda state: None
    def build(*args):
        raise ValueError("invalid selected native path")
    monkeypatch.setattr(m, "street_segment_from_context", build)
    mode = SimpleNamespace(name="CAR" if cause == "mode" else "WALK")
    with pytest.raises((ValueError, RuntimeError)):
        with m.correct_street_geometries(r5py) as audit:
            module.TripPlanner()._street_segment_from_router_state("state", mode)
    assert audit["restored"] and module.TripPlanner._street_segment_from_router_state is original


@pytest.mark.parametrize("cause", ["version", "threads", "source", "already_modified"])
def test_unsupported_runtime_is_refused_before_method_changes(runtime, cause):
    r5py, module, _, source = runtime
    if cause == "version": r5py.__version__ = "2.0"
    if cause == "threads": r5py.DetailedItineraries.NUM_THREADS = 2
    if cause == "source": source.write_text("changed")
    if cause == "already_modified": module.TripPlanner._street_segment_from_router_state = lambda *a: None
    current = module.TripPlanner._street_segment_from_router_state
    with pytest.raises(RuntimeError):
        with m.correct_street_geometries(r5py):
            pytest.fail("Unsupported runtime was accepted")
    assert module.TripPlanner._street_segment_from_router_state is current
