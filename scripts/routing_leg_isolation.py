"""Opt-in leg snapshots for the isolated r5py 1.1.7 smoke-test worker.

The reviewed planner reuses mutable access/egress legs across alternatives.
Snapshotting a leg when it is prepended to a Trip preserves that alternative's
state before the cache is reused. This does not reconstruct timestamps or alter
the route search. A shallow copy is sufficient for the reviewed leg attributes:
scalar values, immutable date/time values, and Shapely 2 geometries.

The context temporarily changes one process-wide method. Use it only in the
fresh smoke worker with one routing job, not as a general application patch.
Version and source checks guard compatibility; they are not a security sandbox.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import hashlib
import importlib
import inspect
from pathlib import Path


ADAPTER_NAME = "r5py-cached-leg-isolation"
ADAPTER_VERSION = 1
SUPPORTED_R5PY = "1.1.7"
SOURCE_SHA256 = {
    "r5/trip_leg.py": "1270678a17061467609296084bcf283bd472728729d13680614f839d6a9a31ea",
    "r5/trip_planner.py": "541bcf3ec644bb717195518699ad540d1c448330539e26b1f36cd850ff7674a7",
    "r5/trip.py": "ae7b1123d35d780cc5c10a407bc61dfb6017f919586259139b68f637422e96a9",
}


def _verified_runtime(r5py):
    """Return the reviewed classes/method, refusing incompatible runtime state."""
    if getattr(r5py, "__version__", None) != SUPPORTED_R5PY:
        raise RuntimeError("Cached-leg isolation requires r5py 1.1.7.")
    jobs = r5py.DetailedItineraries.NUM_THREADS
    if type(jobs) is not int or jobs != 1:
        raise RuntimeError("Cached-leg isolation requires one Python routing job.")

    package = Path(r5py.__file__).resolve().parent
    hashes = {}
    for relative, expected in SOURCE_SHA256.items():
        source = (package / relative).read_bytes().replace(b"\r\n", b"\n")
        actual = hashlib.sha256(source).hexdigest()
        if actual != expected:
            raise RuntimeError(f"Cached-leg isolation source mismatch: {relative}.")
        hashes[relative] = actual

    leg_module = importlib.import_module("r5py.r5.trip_leg")
    trip_module = importlib.import_module("r5py.r5.trip")
    planner_module = importlib.import_module("r5py.r5.trip_planner")
    for module, relative in (
        (leg_module, "r5/trip_leg.py"),
        (trip_module, "r5/trip.py"),
        (planner_module, "r5/trip_planner.py"),
    ):
        if Path(module.__file__).resolve() != (package / relative).resolve():
            raise RuntimeError("Cached-leg isolation loaded an unexpected module.")

    leg_class = leg_module.TripLeg
    trip_class = trip_module.Trip
    original_add = leg_class.__add__
    if (
        not inspect.isfunction(original_add)
        or original_add.__module__ != leg_module.__name__
        or original_add.__qualname__ != "TripLeg.__add__"
        or hasattr(original_add, "__wrapped__")
        or Path(original_add.__code__.co_filename).resolve()
        != (package / "r5/trip_leg.py").resolve()
        or inspect.getmodule(original_add) is not leg_module
        or planner_module.Trip is not trip_class
    ):
        raise RuntimeError("Cached-leg isolation found an already modified runtime.")
    return leg_class, trip_class, original_add, hashes


@contextmanager
def isolate_cached_legs(r5py):
    """Snapshot each prepended leg and restore the upstream method on exit.

    Yield a JSON-safe audit dictionary. Its ``applied`` field records whether
    the adapter was used, and ``restored`` becomes true after context exit.
    Unsupported source/version/runtime state raises before any method changes.
    """
    leg_class, trip_class, original_add, hashes = _verified_runtime(r5py)
    audit = {
        "name": ADAPTER_NAME,
        "version": ADAPTER_VERSION,
        "r5py": SUPPORTED_R5PY,
        "source_sha256": hashes,
        "applied": False,
        "restored": False,
        "legs_snapshotted": 0,
    }

    def isolated_add(self, other):
        if isinstance(other, trip_class):
            snapshot = copy.copy(self)
            if snapshot is self:
                raise RuntimeError("Cached-leg isolation could not create a snapshot.")
            audit["legs_snapshotted"] += 1
            return original_add(snapshot, other)
        return original_add(self, other)

    leg_class.__add__ = isolated_add
    audit["applied"] = True
    try:
        yield audit
    finally:
        current_add = leg_class.__add__
        leg_class.__add__ = original_add
        audit["restored"] = leg_class.__add__ is original_add
        if current_add is not isolated_add:
            raise RuntimeError("Cached-leg isolation was modified during its scope.")
