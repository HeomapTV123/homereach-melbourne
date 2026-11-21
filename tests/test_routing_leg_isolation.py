"""Cached itinerary legs keep each alternative's state without a JVM.

The small source-backed stand-ins below expose the relevant upstream ownership
contract. They deliberately reuse mutable leg instances; the adapter, rather
than the stand-in, must prevent later alternatives from changing earlier trips.
"""
from __future__ import annotations

import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/routing_leg_isolation.py"
SPEC = importlib.util.spec_from_file_location("routing_leg_isolation_under_test", SCRIPT)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)

TRIP_SOURCE = """class Trip:
    def __init__(self, legs=None):
        self.legs = [] if legs is None else list(legs)
"""
LEG_SOURCE = """from .trip import Trip

class TripLeg:
    def __init__(self, mode, geometry):
        self.transport_mode = mode
        self.geometry = geometry
        self.distance = 12.0
        self.travel_time = None
        self.wait_time = None
        self.departure_time = None
        self.arrival_time = None
        self.route_id = 'SMOKE_BUS' if mode == 'BUS' else None

    def __add__(self, other):
        if isinstance(other, self.__class__):
            return Trip([self, other])
        if isinstance(other, Trip):
            other.legs = [self] + other.legs
            return other
        raise TypeError('unsupported itinerary operand')

class AccessLeg(TripLeg):
    pass

class EgressLeg(TripLeg):
    pass
"""
PLANNER_SOURCE = "from .trip import Trip\n"


@pytest.fixture
def reviewed_runtime(tmp_path, monkeypatch):
    """Provide real source/provenance checks, without importing real r5py."""
    package = tmp_path / "r5py"
    (package / "r5").mkdir(parents=True)
    root = ModuleType("r5py")
    root.__file__ = str(package / "__init__.py")
    root.__path__ = [str(package)]
    root.__version__ = "1.1.7"
    root.DetailedItineraries = SimpleNamespace(NUM_THREADS=1)
    nested = ModuleType("r5py.r5")
    nested.__path__ = [str(package / "r5")]
    monkeypatch.setitem(sys.modules, root.__name__, root)
    monkeypatch.setitem(sys.modules, nested.__name__, nested)
    modules = {}
    hashes = {}
    for name, source in (("trip", TRIP_SOURCE), ("trip_leg", LEG_SOURCE),
                         ("trip_planner", PLANNER_SOURCE)):
        relative = f"r5/{name}.py"
        path = package / relative
        path.write_text(source, encoding="utf-8", newline="\n")
        module_spec = importlib.util.spec_from_file_location(f"r5py.r5.{name}", path)
        module = importlib.util.module_from_spec(module_spec)
        monkeypatch.setitem(sys.modules, module.__name__, module)
        module_spec.loader.exec_module(module)
        modules[name] = module
        hashes[relative] = hashlib.sha256(source.encode("utf-8")).hexdigest()
    monkeypatch.setattr(m, "SOURCE_SHA256", hashes)
    return SimpleNamespace(package=package, r5py=root, modules=modules,
                           Trip=modules["trip"].Trip, TripLeg=modules["trip_leg"].TripLeg,
                           AccessLeg=modules["trip_leg"].AccessLeg,
                           EgressLeg=modules["trip_leg"].EgressLeg, hashes=hashes)


def set_times(leg, departure, duration, wait=0):
    leg.departure_time = departure
    leg.travel_time = datetime.timedelta(seconds=duration)
    leg.arrival_time = departure + leg.travel_time
    leg.wait_time = datetime.timedelta(seconds=wait)


def test_each_alternative_owns_access_and_egress_timestamps(reviewed_runtime):
    runtime = reviewed_runtime
    original = runtime.TripLeg.__add__
    geometry = ((0.0, 0.0), (0.001, 0.0))  # Immutable, like reviewed Shapely 2 geometry.
    access = runtime.AccessLeg("WALK", geometry)
    egress = runtime.EgressLeg("WALK", geometry)
    trips = []
    expected = []
    with m.isolate_cached_legs(runtime.r5py) as audit:
        for offset in (0, 5, 10):
            departure = datetime.datetime(2026, 10, 13, 8, offset)
            set_times(access, departure, 12)
            bus = runtime.TripLeg("BUS", geometry)
            set_times(bus, departure + datetime.timedelta(minutes=5), 300, wait=288)
            set_times(egress, bus.arrival_time + datetime.timedelta(seconds=60), 20)
            trip = access + (bus + (egress + runtime.Trip()))
            trips.append(trip)
            expected.append((access.departure_time, access.arrival_time,
                             bus.departure_time, egress.departure_time, egress.arrival_time))
        # A later cache update must not change any trip already assembled.
        access.departure_time = datetime.datetime(2027, 1, 1)
        access.arrival_time = datetime.datetime(2027, 1, 2)
        egress.departure_time = datetime.datetime(2027, 2, 1)
        egress.arrival_time = datetime.datetime(2027, 2, 2)
        for trip, times in zip(trips, expected):
            a, b, e = trip.legs
            assert (a.departure_time, a.arrival_time, b.departure_time,
                    e.departure_time, e.arrival_time) == times
            assert a is not access and e is not egress
            assert type(a) is runtime.AccessLeg and type(e) is runtime.EgressLeg
            assert [leg.transport_mode for leg in trip.legs] == ["WALK", "BUS", "WALK"]
            assert [leg.route_id for leg in trip.legs] == [None, "SMOKE_BUS", None]
            assert all(leg.geometry is geometry and leg.distance == 12.0 for leg in trip.legs)
            assert b.wait_time == b.departure_time - a.arrival_time
            assert e.departure_time - b.arrival_time == datetime.timedelta(seconds=60)
        assert len({id(leg) for trip in trips for leg in trip.legs}) == 9
        assert audit["applied"] is True and audit["restored"] is False
        assert audit["legs_snapshotted"] == 9
    assert runtime.TripLeg.__add__ is original
    assert audit["restored"] is True
    assert audit["source_sha256"] == runtime.hashes
    assert audit["name"] == m.ADAPTER_NAME
    assert audit["version"] == m.ADAPTER_VERSION
    assert json.loads(json.dumps(audit)) == audit


def test_standin_reproduces_upstream_alias_without_adapter(reviewed_runtime):
    runtime = reviewed_runtime
    access = runtime.AccessLeg("WALK", ())
    first_departure = datetime.datetime(2026, 10, 13, 8)
    set_times(access, first_departure, 12)
    first = access + runtime.Trip()
    set_times(access, first_departure + datetime.timedelta(minutes=5), 12)
    second = access + runtime.Trip()
    assert first.legs[0] is second.legs[0] is access
    assert first.legs[0].departure_time != first_departure


def test_method_is_restored_when_routing_raises(reviewed_runtime):
    original = reviewed_runtime.TripLeg.__add__
    with pytest.raises(ValueError, match="routing failed"):
        with m.isolate_cached_legs(reviewed_runtime.r5py) as audit:
            raise ValueError("routing failed")
    assert reviewed_runtime.TripLeg.__add__ is original
    assert audit["applied"] is True and audit["restored"] is True


def test_other_addition_contracts_are_unchanged(reviewed_runtime):
    runtime = reviewed_runtime
    first = runtime.TripLeg("WALK", ())
    second = runtime.TripLeg("BUS", ())
    with m.isolate_cached_legs(runtime.r5py) as audit:
        pair = first + second
        assert pair.legs[0] is first and pair.legs[1] is second
        with pytest.raises(TypeError, match="unsupported itinerary operand"):
            first + object()
        assert audit["legs_snapshotted"] == 0


@pytest.mark.parametrize("version", [None, "1.1.6", "1.1.8", "1.1.7+local"])
def test_unreviewed_version_is_rejected_before_binding_changes(reviewed_runtime, version):
    runtime = reviewed_runtime
    original = runtime.TripLeg.__add__
    runtime.r5py.__version__ = version
    with pytest.raises(RuntimeError, match="requires r5py 1.1.7"):
        with m.isolate_cached_legs(runtime.r5py):
            pytest.fail("An unsupported version entered the adapter scope.")
    assert runtime.TripLeg.__add__ is original


@pytest.mark.parametrize("jobs", [0, 2, -1, True, 1.0, "1"])
def test_only_one_integer_routing_job_is_supported(reviewed_runtime, jobs):
    runtime = reviewed_runtime
    original = runtime.TripLeg.__add__
    runtime.r5py.DetailedItineraries.NUM_THREADS = jobs
    with pytest.raises(RuntimeError, match="one Python routing job"):
        with m.isolate_cached_legs(runtime.r5py):
            pytest.fail("Multiple or ambiguous jobs entered the adapter scope.")
    assert runtime.TripLeg.__add__ is original


@pytest.mark.parametrize("relative", ["r5/trip.py", "r5/trip_leg.py", "r5/trip_planner.py"])
def test_changed_source_is_rejected_before_binding_changes(reviewed_runtime, relative):
    runtime = reviewed_runtime
    original = runtime.TripLeg.__add__
    path = runtime.package / relative
    path.write_bytes(path.read_bytes() + b"\n# an unreviewed change\n")
    with pytest.raises(RuntimeError, match="source mismatch"):
        with m.isolate_cached_legs(runtime.r5py):
            pytest.fail("Changed upstream source entered the adapter scope.")
    assert runtime.TripLeg.__add__ is original


def test_source_gate_accepts_crlf_equivalent_bytes(reviewed_runtime):
    for relative in reviewed_runtime.hashes:
        path = reviewed_runtime.package / relative
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    with m.isolate_cached_legs(reviewed_runtime.r5py) as audit:
        assert audit["source_sha256"] == reviewed_runtime.hashes
    assert audit["restored"] is True


def test_source_missing_is_rejected_without_method_changes(reviewed_runtime):
    original = reviewed_runtime.TripLeg.__add__
    (reviewed_runtime.package / "r5/trip_planner.py").unlink()
    with pytest.raises(OSError):
        with m.isolate_cached_legs(reviewed_runtime.r5py):
            pytest.fail("Missing reviewed source entered the adapter scope.")
    assert reviewed_runtime.TripLeg.__add__ is original


def test_module_from_another_installation_is_rejected(reviewed_runtime):
    runtime = reviewed_runtime
    original = runtime.TripLeg.__add__
    runtime.modules["trip"].__file__ = str(runtime.package / "unexpected_trip.py")
    with pytest.raises(RuntimeError, match="unexpected module"):
        with m.isolate_cached_legs(runtime.r5py):
            pytest.fail("A mismatched module entered the adapter scope.")
    assert runtime.TripLeg.__add__ is original


def test_preexisting_method_replacement_is_left_untouched(reviewed_runtime, monkeypatch):
    runtime = reviewed_runtime
    replacement = lambda self, other: other
    monkeypatch.setattr(runtime.TripLeg, "__add__", replacement)
    with pytest.raises(RuntimeError, match="already modified runtime"):
        with m.isolate_cached_legs(runtime.r5py):
            pytest.fail("A previously modified method entered the adapter scope.")
    assert runtime.TripLeg.__add__ is replacement


def test_reentrant_context_is_rejected_without_disturbing_outer_scope(reviewed_runtime):
    runtime = reviewed_runtime
    original = runtime.TripLeg.__add__
    with m.isolate_cached_legs(runtime.r5py) as audit:
        installed = runtime.TripLeg.__add__
        with pytest.raises(RuntimeError, match="already modified runtime"):
            with m.isolate_cached_legs(runtime.r5py):
                pytest.fail("Nested isolation should not replace the active wrapper.")
        assert runtime.TripLeg.__add__ is installed
        assert audit["restored"] is False
    assert runtime.TripLeg.__add__ is original
    assert audit["restored"] is True


def test_failed_snapshot_cannot_claim_isolation(reviewed_runtime, monkeypatch):
    runtime = reviewed_runtime
    original = runtime.TripLeg.__add__
    monkeypatch.setattr(m.copy, "copy", lambda value: value)
    with pytest.raises(RuntimeError, match="could not create a snapshot"):
        with m.isolate_cached_legs(runtime.r5py) as audit:
            runtime.AccessLeg("WALK", ()) + runtime.Trip()
    assert audit["legs_snapshotted"] == 0
    assert audit["restored"] is True
    assert runtime.TripLeg.__add__ is original


def test_interfering_patch_causes_failure_after_restoring_original(reviewed_runtime):
    runtime = reviewed_runtime
    original = runtime.TripLeg.__add__
    with pytest.raises(RuntimeError, match="modified during its scope"):
        with m.isolate_cached_legs(runtime.r5py) as audit:
            runtime.TripLeg.__add__ = lambda self, other: other
    assert runtime.TripLeg.__add__ is original
    assert audit["restored"] is True
