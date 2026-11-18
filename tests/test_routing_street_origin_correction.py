"""Scope, ordering and refusal contracts without importing a JVM."""
from __future__ import annotations

import functools
import hashlib
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/routing_street_origin_correction.py"
SPEC = importlib.util.spec_from_file_location("origin_correction_under_test", SCRIPT)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)

PLANNER_SOURCE = """import functools
import com
class TripPlanner:
    @property
    def direct_paths(self):
        return []
    @functools.cached_property
    def _transit_access_paths(self):
        return {}
    @functools.cached_property
    def _transit_egress_paths(self):
        return {}
"""


class NativeRouter:
    def __init__(self, street_layer):
        self.street_layer = street_layer
        self.streetMode = "WALK"
        self.profileRequest = SimpleNamespace(reverseSearch=False)
        self.calls = []
        self.state = object()
        self.found_origin = True

    def setOrigin(self, lat, lon):
        self.calls.append(("origin", lat, lon))
        return self.found_origin

    def setDestination(self, lat, lon):
        self.calls.append(("destination", lat, lon))

    def route(self):
        assert any(call[0] == "helper" for call in self.calls)
        self.calls.append(("route",))

    def getState(self, split):
        self.calls.append(("point_state", split))
        return self.state

    def getStateAtVertex(self, vertex):
        self.calls.append(("vertex_state", vertex))
        return self.state


class Helper:
    @staticmethod
    def repairReverseOrigin(router):
        assert router.calls[-1][0] == "origin"
        assert not any(call[0] == "route" for call in router.calls)
        router.calls.append(("helper",))
        return 2 if router.profileRequest.reverseSearch else 0


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    root = ModuleType("r5py")
    package = tmp_path / "r5py"
    (package / "r5").mkdir(parents=True)
    root.__file__ = str(package / "__init__.py")
    root.__path__ = [str(package)]
    root.__version__ = "1.1.7"
    root.DetailedItineraries = SimpleNamespace(NUM_THREADS=1)
    nested = ModuleType("r5py.r5")
    nested.__path__ = [str(package / "r5")]
    com = SimpleNamespace(conveyal=SimpleNamespace(r5=SimpleNamespace(
        streets=SimpleNamespace(StreetRouter=NativeRouter, marker="native street namespace"),
        profile="unchanged profile namespace")))
    monkeypatch.setitem(sys.modules, "r5py", root)
    monkeypatch.setitem(sys.modules, "r5py.r5", nested)
    monkeypatch.setitem(sys.modules, "com", com)
    path = package / "r5/trip_planner.py"
    path.write_text(PLANNER_SOURCE)
    spec = importlib.util.spec_from_file_location("r5py.r5.trip_planner", path)
    planner = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, planner.__name__, planner)
    spec.loader.exec_module(planner)
    hashes = {"r5/trip_planner.py": hashlib.sha256(PLANNER_SOURCE.encode()).hexdigest()}
    monkeypatch.setattr(m, "SOURCE_SHA256", hashes)
    compilation = {"java_source_sha256": m.JAVA_SOURCE_SHA256, "class_sha256": "mock-class",
                   "compiler_java_version": "21-test", "compiled_in_temporary_workspace": True,
                   "original_jar_sha256": m.JAR_SHA256}
    loader = SimpleNamespace(closed=False)
    def close_loader():
        loader.closed = True
    loader.close = close_loader
    monkeypatch.setattr(m, "_compile_helper", lambda work, jar: (Helper, compilation, loader))
    return SimpleNamespace(root=root, planner=planner, com=com, path=path,
                           work=tmp_path, jar=tmp_path / "r5.jar", hashes=hashes, loader=loader)


def router_from(runtime):
    return runtime.planner.com.conveyal.r5.streets.StreetRouter("layer")


def test_forward_search_captures_native_context_and_restores_namespace(runtime):
    with m.correct_street_origins(runtime.root, runtime.work, runtime.jar) as audit:
        router = router_from(runtime)
        assert runtime.planner.com.conveyal.r5.profile == "unchanged profile namespace"
        assert runtime.planner.com.conveyal.r5.streets.marker == "native street namespace"
        router.setOrigin(0.018, 0.0061)
        router.setDestination(0.018, 0.0299)
        router.route()
        state = router.getState("destination split")
        context = m.context_for_state(state)
        assert context == {"router": router._native, "origin_lon_lat": (0.0061, 0.018),
                           "destination_lon_lat": (0.0299, 0.018), "reverse": False}
        context["origin_lon_lat"] = (99, 99)
        assert m.context_for_state(state)["origin_lon_lat"] == (0.0061, 0.018)
        assert audit["reverse_states_rebuilt"] == 0
        assert audit["origins_initialized"] == 1
        assert audit["states_registered"] == 1
        assert audit["routers_created"] == 1
        assert not audit["restored"]
    assert audit["restored"]
    assert audit["helper_loader_closed"] and runtime.loader.closed
    assert runtime.planner.com is runtime.com
    with pytest.raises(RuntimeError, match="No reviewed native router context"):
        m.context_for_state(state)


def test_reverse_stop_search_initializes_before_route_and_registers_actual_state(runtime):
    with m.correct_street_origins(runtime.root, runtime.work, runtime.jar) as audit:
        router = router_from(runtime)
        router.profileRequest = SimpleNamespace(reverseSearch=True)
        router.setOrigin(0.018, 0.0299)
        router.route()
        state = router.getStateAtVertex(49)
        assert router._native.calls == [("origin", 0.018, 0.0299), ("helper",),
                                        ("route",), ("vertex_state", 49)]
        assert m.context_for_state(state)["reverse"] is True
        assert m.context_for_state(state)["destination_lon_lat"] is None
        assert audit["reverse_states_rebuilt"] == 2


def test_exception_restores_namespace_and_clears_context(runtime):
    with pytest.raises(ValueError, match="query failed"):
        with m.correct_street_origins(runtime.root, runtime.work, runtime.jar) as audit:
            router = router_from(runtime)
            router.setOrigin(1, 2)
            router.route()
            state = router.getStateAtVertex(3)
            raise ValueError("query failed")
    assert runtime.planner.com is runtime.com
    assert audit["restored"]
    assert audit["helper_loader_closed"] and runtime.loader.closed
    with pytest.raises(RuntimeError):
        m.context_for_state(state)


def test_nested_scope_refused_without_losing_outer_scope(runtime):
    with m.correct_street_origins(runtime.root, runtime.work, runtime.jar):
        outer = runtime.planner.com
        with pytest.raises(RuntimeError, match="already active"):
            with m.correct_street_origins(runtime.root, runtime.work, runtime.jar):
                pytest.fail("Nested context must not start")
        assert runtime.planner.com is outer
    assert runtime.planner.com is runtime.com


def test_changed_namespace_is_restored_and_reported(runtime):
    with pytest.raises(RuntimeError, match="namespace changed"):
        with m.correct_street_origins(runtime.root, runtime.work, runtime.jar) as audit:
            runtime.planner.com = object()
    assert runtime.planner.com is runtime.com
    assert audit["restored"]


@pytest.mark.parametrize("mode", ["CAR", "BICYCLE", "TRANSIT"])
def test_non_walk_refused_before_origin(runtime, mode):
    with m.correct_street_origins(runtime.root, runtime.work, runtime.jar):
        router = router_from(runtime)
        router.streetMode = mode
        with pytest.raises(RuntimeError, match="WALK only"):
            router.setOrigin(1, 2)
        assert not router._native.calls


def test_reverse_point_destination_refused(runtime):
    with m.correct_street_origins(runtime.root, runtime.work, runtime.jar):
        router = router_from(runtime)
        router.profileRequest.reverseSearch = True
        router.setOrigin(1, 2)
        with pytest.raises(RuntimeError, match="Reverse point-to-point"):
            router.setDestination(3, 4)
        assert not any(call[0] == "destination" for call in router._native.calls)


def test_repeat_origin_route_and_late_mode_change_are_refused(runtime):
    with m.correct_street_origins(runtime.root, runtime.work, runtime.jar):
        router = router_from(runtime)
        with pytest.raises(RuntimeError, match="fresh origin"):
            router.setDestination(1, 2)
        router.setOrigin(1, 2)
        with pytest.raises(RuntimeError, match="fresh router"):
            router.setOrigin(1, 2)
        router.streetMode = "CAR"
        with pytest.raises(RuntimeError, match="WALK only"):
            router.route()
        router.streetMode = "WALK"
        router.route()
        with pytest.raises(RuntimeError, match="one search"):
            router.route()


def test_missing_origin_edge_stops_before_helper_or_search(runtime):
    with m.correct_street_origins(runtime.root, runtime.work, runtime.jar):
        router = router_from(runtime)
        router.found_origin = False
        with pytest.raises(RuntimeError, match="No native walking edge"):
            router.setOrigin(1, 2)
        assert router._native.calls == [("origin", 1, 2)]


def test_state_before_search_and_point_state_without_destination_refused(runtime):
    with m.correct_street_origins(runtime.root, runtime.work, runtime.jar):
        router = router_from(runtime)
        router.setOrigin(1, 2)
        with pytest.raises(RuntimeError, match="unsearched"):
            router.getStateAtVertex(49)
        with pytest.raises(RuntimeError, match="point destination"):
            router.getState("some split")


@pytest.mark.parametrize("version", [None, "1.1.6", "1.2.0"])
def test_other_versions_refused(runtime, version):
    runtime.root.__version__ = version
    with pytest.raises(RuntimeError, match="requires r5py 1.1.7"):
        with m.correct_street_origins(runtime.root, runtime.work, runtime.jar):
            pytest.fail("Incompatible version")
    assert runtime.planner.com is runtime.com


@pytest.mark.parametrize("jobs", [0, 2, True, "1"])
def test_parallel_or_malformed_job_count_refused(runtime, jobs):
    runtime.root.DetailedItineraries.NUM_THREADS = jobs
    with pytest.raises(RuntimeError, match="one Python routing job"):
        m._verified_runtime(runtime.root)


def test_source_change_refused(runtime):
    runtime.path.write_text(PLANNER_SOURCE + "\n# different source\n")
    with pytest.raises(RuntimeError, match="source mismatch"):
        m._verified_runtime(runtime.root)


def test_windows_crlf_source_has_same_canonical_fingerprint(runtime):
    runtime.path.write_bytes(PLANNER_SOURCE.replace("\n", "\r\n").encode())
    _, hashes = m._verified_runtime(runtime.root)
    assert hashes == runtime.hashes


def test_already_wrapped_planner_method_refused(runtime):
    original = runtime.planner.TripPlanner.direct_paths.fget
    @functools.wraps(original)
    def wrapper(self):
        return original(self)
    runtime.planner.TripPlanner.direct_paths = property(wrapper)
    with pytest.raises(RuntimeError, match="already modified planner"):
        m._verified_runtime(runtime.root)


def test_reviewed_java_helper_bytes_match_declared_fingerprint():
    source = m.JAVA_SOURCE.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(source).hexdigest() == m.JAVA_SOURCE_SHA256
