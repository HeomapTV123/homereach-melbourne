"""Build WALK geometry from the native state chain and actual edge splits.

This is an experimental construction helper for the pinned single-worker
routing integration. It preserves the route chosen by the native search,
including explicit off-street split connectors, and never changes its costs.
It does not use the independent fixture oracle or repair serialized results.
"""
from __future__ import annotations

import math
from contextlib import contextmanager
import hashlib
import importlib
import inspect
from pathlib import Path
from types import SimpleNamespace


COORDINATE_TOLERANCE = 2e-7  # Two native fixed-coordinate units (degrees).
MAX_STATE_CHAIN = 100_000
ADAPTER_NAME = "r5py-native-split-walking-geometry"
ADAPTER_VERSION = 1
SOURCE_SHA256 = {
    "r5/trip_planner.py": "541bcf3ec644bb717195518699ad540d1c448330539e26b1f36cd850ff7674a7",
}


def _point(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("Expected a longitude/latitude coordinate pair.")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value):
        raise ValueError("Coordinates must be finite numbers.")
    x, y = map(float, value)
    if not math.isfinite(x) or not math.isfinite(y) or not -180 <= x <= 180 or not -90 <= y <= 90:
        raise ValueError("Coordinates lie outside finite longitude/latitude bounds.")
    return x, y


def _same(first, second):
    return max(abs(a - b) for a, b in zip(first, second)) <= COORDINATE_TOLERANCE


def _edge(edges, identifier):
    if type(identifier) is not int or identifier < 0 or identifier not in edges:
        raise ValueError("A state refers to an unavailable native edge.")
    edge = edges[identifier]
    if any(type(edge.get(k)) is not int or edge[k] < 0 for k in ("from_vertex", "to_vertex")):
        raise ValueError("A native edge has invalid endpoint vertices.")
    coordinates = edge.get("coordinates")
    if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
        raise ValueError("A native edge requires at least two coordinates.")
    return edge, [_point(point) for point in coordinates]


def _split_parts(split, edges):
    """Return pair-forward geometry before/after the actual native split."""
    if not isinstance(split, dict):
        raise ValueError("The actual native edge split is required.")
    edge_id = split.get("edge")
    edge, coordinates = _edge(edges, edge_id)
    if edge_id % 2 or (edge["from_vertex"], edge["to_vertex"]) != (split.get("vertex0"), split.get("vertex1")):
        raise ValueError("Split must refer to the forward edge and its actual vertices.")
    segment, fraction = split.get("segment"), split.get("fraction")
    if type(segment) is not int or not 0 <= segment < len(coordinates) - 1:
        raise ValueError("Native split segment lies outside the edge geometry.")
    if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) or not math.isfinite(fraction) or not 0 <= fraction <= 1:
        raise ValueError("Native split fraction must lie in the segment.")
    point = _point(split.get("point"))
    first, second = coordinates[segment:segment + 2]
    interpolated = tuple(a + fraction * (b - a) for a, b in zip(first, second))
    if not _same(interpolated, point):
        raise ValueError("Native split coordinate disagrees with its segment/fraction.")
    return coordinates[:segment + 1] + [point], [point] + coordinates[segment + 1:]


def _append_path(output, part):
    if not part or not _same(output[-1], part[0]):
        raise ValueError("Native edge geometry is disconnected from the chosen state chain.")
    for point in part[1:]:
        if point != output[-1]:
            output.append(point)


def build_path_coordinates(states, edges, *, origin, origin_split,
                           destination=None, destination_split=None, reverse=False):
    """Reconstruct the searched path from plain snapshots, without GIS imports.

    ``states`` are in search order, from the initial endpoint state to the
    selected terminal state. Edges have directed from/to vertices and geometry.
    A destination split is present only for a coordinate-to-coordinate search;
    access/egress searches end at the selected native transit-stop vertex.
    Reverse searches are returned in traveller order after reconstruction.
    """
    if type(reverse) is not bool or not isinstance(states, (list, tuple)) or not states:
        raise ValueError("A nonempty native state chain and explicit search direction are required.")
    if len(states) > MAX_STATE_CHAIN:
        raise ValueError("Native state chain exceeds the reviewed size bound.")
    for state in states:
        if not isinstance(state, dict) or type(state.get("vertex")) is not int or type(state.get("back_edge")) is not int:
            raise ValueError("Native state identifiers are malformed.")
    if (destination is None) != (destination_split is None):
        raise ValueError("Requested destination and native destination split must be supplied together.")
    left, right = _split_parts(origin_split, edges)
    first = states[0]
    if first["vertex"] not in (origin_split["vertex0"], origin_split["vertex1"]):
        raise ValueError("Initial state is not an endpoint of the actual origin split.")
    at_zero = first["vertex"] == origin_split["vertex0"]
    expected_edge = origin_split["edge"] + int(at_zero != reverse)
    if first["back_edge"] != expected_edge:
        raise ValueError("Initial state back-edge does not match its vertex/search direction.")
    point = _point(origin)
    split_point = _point(origin_split["point"])
    output = [point]
    if point != split_point:
        output.append(split_point)  # Native off-street link, retained explicitly.
    _append_path(output, list(reversed(left)) if at_zero else right)

    for index, state in enumerate(states[1:], start=1):
        previous = states[index - 1]
        if previous["vertex"] < 0:
            raise ValueError("A terminal coordinate state occurs before the end of the path.")
        if state["vertex"] == -1:
            if index != len(states) - 1 or destination_split is None:
                raise ValueError("Coordinate terminal state has no matching destination split.")
            left, right = _split_parts(destination_split, edges)
            at_zero = previous["vertex"] == destination_split["vertex0"]
            if previous["vertex"] not in (destination_split["vertex0"], destination_split["vertex1"]):
                raise ValueError("Destination state does not approach from its split endpoint.")
            expected_edge = destination_split["edge"] + int(at_zero == reverse)
            if state["back_edge"] != expected_edge:
                raise ValueError("Destination back-edge does not match its endpoint/search direction.")
            _append_path(output, left if at_zero else list(reversed(right)))
            requested_destination = _point(destination)
            if requested_destination != output[-1]:
                output.append(requested_destination)
        elif state["vertex"] >= 0:
            edge, coordinates = _edge(edges, state["back_edge"])
            expected_vertices = ((edge["to_vertex"], edge["from_vertex"]) if reverse
                                 else (edge["from_vertex"], edge["to_vertex"]))
            if expected_vertices != (previous["vertex"], state["vertex"]):
                raise ValueError("Traversed native edge disagrees with adjacent state vertices.")
            _append_path(output, list(reversed(coordinates)) if reverse else coordinates)
        else:
            raise ValueError("Unsupported native terminal vertex.")
    if destination is not None and states[-1]["vertex"] != -1:
        raise ValueError("Coordinate destination lacks its partial terminal state.")
    if len(output) == 1:
        output.append(output[0])  # Preserve a genuine zero-length native path.
    return list(reversed(output)) if reverse else output


def street_segment_from_context(router_state, context):
    """Construct geometry before leg assembly, retaining native distance/time.

    Context is supplied by the source-verified router proxy when returning the
    state: Java ``router``, requested ``origin_lon_lat`` and optional destination.
    All split coordinates and traversed edges are read from that same router.
    """
    import shapely

    router = context["router"]
    reverse = context["reverse"]
    if type(reverse) is not bool or reverse != bool(router.profileRequest.reverseSearch):
        raise ValueError("Geometry context search direction disagrees with its native router.")
    native_states, seen = [], set()
    current = router_state
    while current is not None:
        if current in seen or len(native_states) >= MAX_STATE_CHAIN:
            raise ValueError("Cyclic or excessive native state chain.")
        seen.add(current)
        native_states.append({"vertex": int(current.vertex), "back_edge": int(current.backEdge)})
        current = current.backState
    native_states.reverse()
    layer = router.streetLayer
    edges = {}

    def load_edge(identifier):
        identifier = int(identifier)
        if identifier not in edges:
            cursor = layer.edgeStore.getCursor(identifier)
            edges[identifier] = {"from_vertex": int(cursor.getFromVertex()),
                                 "to_vertex": int(cursor.getToVertex()),
                                 "coordinates": [(float(c.x), float(c.y))
                                                 for c in cursor.getGeometry().getCoordinates()]}

    def split_snapshot(split):
        if split is None:
            raise ValueError("Native router has no required split.")
        load_edge(split.edge)
        return {"edge": int(split.edge), "vertex0": int(split.vertex0), "vertex1": int(split.vertex1),
                "segment": int(split.seg), "fraction": float(split.frac),
                "point": (float(split.fixedLon) / 10_000_000, float(split.fixedLat) / 10_000_000)}

    origin_split = split_snapshot(router.getOriginSplit())
    destination = context.get("destination_lon_lat")
    native_destination_split = router.getDestinationSplit() if destination is not None else None
    if native_destination_split is not None and int(native_destination_split.distanceToEdge_mm) != 0:
        raise ValueError("Off-street coordinate destinations are unsupported: this R5 version omits their connector cost.")
    destination_split = split_snapshot(native_destination_split) if destination is not None else None
    for state in native_states:
        load_edge(state["back_edge"])
    coordinates = build_path_coordinates(native_states, edges, origin=context["origin_lon_lat"],
                                         origin_split=origin_split, destination=destination,
                                         destination_split=destination_split, reverse=reverse)
    return SimpleNamespace(distance=int(router_state.distance), duration=int(router_state.getDurationSeconds()),
                           geometry=shapely.LineString(coordinates))


def _verified_runtime(r5py):
    if getattr(r5py, "__version__", None) != "1.1.7":
        raise RuntimeError("Native split geometry requires r5py 1.1.7.")
    if type(r5py.DetailedItineraries.NUM_THREADS) is not int or r5py.DetailedItineraries.NUM_THREADS != 1:
        raise RuntimeError("Native split geometry requires one Python routing job.")
    package = Path(r5py.__file__).resolve().parent
    hashes = {}
    for relative, expected in SOURCE_SHA256.items():
        actual = hashlib.sha256((package / relative).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        if actual != expected:
            raise RuntimeError(f"Native split geometry source mismatch: {relative}.")
        hashes[relative] = actual
    module = importlib.import_module("r5py.r5.trip_planner")
    path = (package / "r5/trip_planner.py").resolve()
    original = module.TripPlanner._street_segment_from_router_state
    if (Path(module.__file__).resolve() != path or not inspect.isfunction(original)
            or original.__module__ != module.__name__
            or original.__qualname__ != "TripPlanner._street_segment_from_router_state"
            or Path(original.__code__.co_filename).resolve() != path
            or inspect.getmodule(original) is not module or hasattr(original, "__wrapped__")):
        raise RuntimeError("Native split geometry found an already modified planner method.")
    return module.TripPlanner, original, hashes


@contextmanager
def correct_street_geometries(r5py):
    """Construct precise native WALK paths in the guarded fresh worker only."""
    from routing_street_origin_correction import context_for_state

    planner_class, original, hashes = _verified_runtime(r5py)
    audit = {"name": ADAPTER_NAME, "version": ADAPTER_VERSION, "r5py": "1.1.7",
             "source_sha256": hashes, "applied": False, "restored": False,
             "segments_constructed": 0, "native_costs_preserved": True}

    def corrected_segment(planner, router_state, transport_mode):
        if getattr(transport_mode, "name", None) != "WALK":
            raise RuntimeError("Native split geometry supports WALK street legs only.")
        context = context_for_state(router_state)
        if context is None:
            raise RuntimeError("Native split geometry has no verified router context for this state.")
        segment = street_segment_from_context(router_state, context)
        audit["segments_constructed"] += 1
        return segment

    planner_class._street_segment_from_router_state = corrected_segment
    audit["applied"] = True
    try:
        yield audit
    finally:
        current = planner_class._street_segment_from_router_state
        planner_class._street_segment_from_router_state = original
        audit["restored"] = planner_class._street_segment_from_router_state is original
        if current is not corrected_segment:
            raise RuntimeError("Native split geometry was modified during its scope.")
