"""Fresh native baseline for fictional service-day transfers.

Access and egress are fixed artificial costs. Interstop street transfers are
temporarily removed from each newly built fixture network and then restored.
No walking search, transit itinerary serializer or service-day correction runs.
"""
from __future__ import annotations

from contextlib import contextmanager
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback
import warnings
from zipfile import ZipFile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _routing_service_day_anchor_worker import (
    REQUEST_SOURCE_SHA256, active_service_bits, native_catalog, native_costs,
    native_request_fields, native_state_chain,
)
import routing_service_day_transfer as fixture
import run_routing_smoke_test as smoke


def verify_inputs(work: Path) -> None:
    """Require the reviewed engine/streets and every independently staged case."""
    smoke.check_engine(work / smoke.ENGINE_NAME)
    if smoke.sha256(work / "streets.osm.pbf") != smoke.STREET_SHA256:
        raise ValueError("The reviewed street fixture fingerprint changed.")
    for case in fixture.CASES:
        expected = fixture.gtfs_tables(case)
        with ZipFile(work / (case["id"] + ".gtfs.zip")) as archive:
            if len(archive.namelist()) != len(expected) or set(archive.namelist()) != set(expected):
                raise ValueError("Unexpected transfer-fixture timetable members.")
            if any(archive.read(name) != value for name, value in expected.items()):
                raise ValueError("Transfer timetable differs from its fixed case.")


def transfer_inventory(transit) -> list[dict]:
    """Snapshot actual native interstop distances, not inferred walking times."""
    if len(transit.streetTransfers) != len(transit.stopIdForIndex):
        raise ValueError("Native transfer list does not match the stop catalog.")
    rows = []
    for index, entries in enumerate(transit.streetTransfers):
        if entries is None or entries.size() % 2:
            raise ValueError("Malformed native interstop transfer list.")
        transfers = []
        for offset in range(0, entries.size(), 2):
            target, distance = int(entries.get(offset)), int(entries.get(offset + 1))
            if not 0 <= target < len(transit.stopIdForIndex) or distance < 0:
                raise ValueError("Invalid native interstop transfer identity or distance.")
            transfers.append({"to_stop_index": target,
                              "to_stop_id": str(transit.stopIdForIndex.get(target)).split(":")[-1],
                              "distance_mm": distance})
        rows.append({"stop_index": index,
                     "stop_id": str(transit.stopIdForIndex.get(index)).split(":")[-1],
                     "transfers": transfers})
    return rows


@contextmanager
def same_stop_transfer_model(transit, empty_list_factory, empty_int_list_factory):
    """Scope an explicit artificial model: transfers may only stay at one stop."""
    original = transit.streetTransfers
    audit = {"name": "fictional_same_stop_transfers_only", "applied": False,
             "restored": False, "original": transfer_inventory(transit)}
    replacement = empty_list_factory()
    for _ in transit.stopIdForIndex:
        replacement.add(empty_int_list_factory())
    try:
        transit.streetTransfers = replacement
        audit["applied"] = True
        audit["scoped"] = transfer_inventory(transit)
        yield audit
    finally:
        # Capture any mutation before restoring even when the query raises.
        try:
            audit["scoped_after"] = transfer_inventory(transit)
        finally:
            transit.streetTransfers = original
            audit["after"] = transfer_inventory(transit)
            audit["restored"] = audit["after"] == audit["original"]


def execute(work: Path, report: dict) -> None:
    verify_inputs(work)
    jar = work / smoke.ENGINE_NAME
    sys.addaudithook(smoke.python_write_guard(work))
    import configargparse

    configargparse.get_argument_parser(prog="r5py", default_config_files=[])
    sys.argv = [sys.argv[0], "--r5-classpath", str(jar), "--max-memory", "1G",
                "--temporary-directory", str(work / "tmp")]
    import r5py
    import geopandas as gpd
    import jpype
    import rasterio
    from shapely.geometry import Point
    from r5py.r5.regional_task import RegionalTask
    from r5py.util.config import Config

    package = Path(r5py.__file__).resolve().parent
    hashes = {name: hashlib.sha256((package / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
              for name in REQUEST_SOURCE_SHA256}
    if r5py.__version__ != "1.1.7" or hashes != REQUEST_SOURCE_SHA256:
        raise ValueError("Transfer baseline requires the reviewed r5py request/planner sources.")
    report["request_source_sha256"] = hashes
    r5py.DetailedItineraries.NUM_THREADS = 1
    if Path(Config().arguments.r5_classpath).resolve() != jar.resolve():
        raise ValueError("r5py selected a different classpath.")
    system = jpype.JClass("java.lang.System")
    report["engine"] = {
        "r5py": r5py.__version__, "sha256": smoke.sha256(jar),
        "jvm_started": jpype.isJVMStarted(), "java_version": str(system.getProperty("java.version")),
        "max_heap_bytes": int(jpype.JClass("java.lang.Runtime").getRuntime().maxMemory()),
        "classpath_verified": jar.resolve() in [Path(p).resolve() for p in
            str(system.getProperty("java.class.path")).split(os.pathsep)],
        "temporary_directory_verified": Path(str(system.getProperty("java.io.tmpdir"))).resolve().is_relative_to(work / "tmp"),
        "python_routing_jobs": 1, "rasterio_imported": rasterio.__version__,
        "default_configuration_files": [],
        "python_guard_scope": "Python file mutations and socket operations; not a Java/native sandbox",
    }
    NativeRouter = jpype.JClass("com.conveyal.r5.profile.McRaptorSuboptimalPathProfileRouter")
    DominatingList = jpype.JClass("com.conveyal.r5.profile.SuboptimalDominatingList")
    HashMap = jpype.JClass("java.util.HashMap")
    ArrayList = jpype.JClass("java.util.ArrayList")
    IntMap = jpype.JClass("gnu.trove.map.hash.TIntIntHashMap")
    IntList = jpype.JClass("gnu.trove.list.array.TIntArrayList")
    LegMode = jpype.JClass("com.conveyal.r5.api.util.LegMode")
    destinations = gpd.GeoDataFrame({"id": ["synthetic_transfer_destination"]},
                                   geometry=[Point(*fixture.DESTINATION)], crs="EPSG:4326")
    for case in fixture.CASES:
        observed = {"id": case["id"], "civil_departure": case["civil_departure"]}
        report["cases"].append(observed)
        report["networks_attempted"] += 1
        try:
            network = r5py.TransportNetwork(work / "streets.osm.pbf",
                                           [work / (case["id"] + ".gtfs.zip")], allow_errors=False)
            observed["network_timezone"] = str(network.timezone)
            if observed["network_timezone"] != fixture.TIMEZONE:
                raise ValueError("Native network timezone differs from the transfer fixture.")
            transit = network.transit_layer._transit_layer
            observed.update(native_catalog(transit))
            indices = {s["stop_id"]: s["stop_index"] for s in observed["stops"]}
            if len(observed["stops"]) != 3 or set(indices) != {"TRANSFER_A", "TRANSFER_B", "TRANSFER_C"}:
                raise ValueError("The isolated transfer network must contain exactly three fixed stops.")
            access, egress = HashMap(), HashMap()
            for mapping, stop in ((access, "TRANSFER_A"), (egress, "TRANSFER_C")):
                costs = IntMap()
                costs.put(jpype.JInt(indices[stop]), jpype.JInt(12))
                mapping.put(LegMode.WALK, costs)
            request = RegionalTask(
                network, origin=Point(*fixture.ORIGIN), destinations=destinations,
                departure=datetime.datetime.fromisoformat(case["civil_departure"]),
                departure_time_window=datetime.timedelta(seconds=fixture.QUERY_WINDOW_SECONDS),
                transport_modes=[r5py.TransportMode.BUS], access_modes=[r5py.TransportMode.WALK],
                egress_modes=[r5py.TransportMode.WALK], max_time=datetime.timedelta(minutes=30),
                max_time_walking=datetime.timedelta(minutes=30), max_public_transport_rides=2,
                speed_walking=smoke.WALK_SPEED_KMH,
            )
            native = request._regional_task
            native.toLon, native.toLat = fixture.DESTINATION
            observed["request"] = native_request_fields(native)
            observed["costs_before"] = native_costs(access, egress, transit)

            def list_supplier(_departure):
                return DominatingList(max(int(native.suboptimalMinutes), 0))

            try:
                with same_stop_transfer_model(transit, ArrayList, IntList) as model:
                    observed["transfer_model"] = model
                    report["queries_attempted"] += 1
                    router = NativeRouter(network._transport_network, native, access, egress,
                                          list_supplier, None, True)
                    observed["active_services"] = active_service_bits(router, len(observed["services"]))
                    router.route()
                    samples = router.finalStatesByDepartureTime
                    keys = sorted(int(k) for k in samples.keys())
                    if len(keys) > fixture.MAX_SAMPLES:
                        raise ValueError("Native sample count exceeds the fixed transfer baseline limit.")
                    observed["samples"] = []
                    for key in keys:
                        paths = list(samples.get(key))
                        if len(paths) > 10:
                            raise ValueError("Native sample exceeds the transfer path limit.")
                        observed["samples"].append({
                            "departure_seconds": key,
                            "derived_civil_departure": (datetime.datetime.combine(
                                datetime.date.fromisoformat(str(native.date)), datetime.time())
                                + datetime.timedelta(seconds=key)).isoformat(),
                            "chains": [native_state_chain(state) for state in paths],
                        })
            finally:
                observed["request_after"] = native_request_fields(native)
                observed["costs_after"] = native_costs(access, egress, transit)
                observed.update({key + "_after": value for key, value in native_catalog(transit).items()})
        except Exception as error:
            observed["error"] = f"{type(error).__name__}: {error}"
            traceback.print_exc()
    report["status"] = "completed"


def main() -> int:
    work = Path.cwd().resolve()
    if not work.name.startswith("homereach-service-day-transfer-") or work.is_relative_to(smoke.ROOT):
        raise ValueError("Run this worker through run_routing_service_day_transfer_test.py.")
    report = {"status": "failed", "networks_attempted": 0, "queries_attempted": 0,
              "walking_queries_attempted": 0, "cases": [],
              "transit_itinerary_serialization_used": False,
              "native_transit_router_modified": False,
              "fixed_artificial_access_egress_costs": True,
              "interstop_transfer_model": "scoped_empty_street_transfers",
              "physical_walking_validated": False}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            execute(work, report)
        except Exception as error:
            report["error"] = f"{type(error).__name__}: {error}"
            traceback.print_exc()
        report["warnings"] = sorted({str(w.message) for w in caught})
    with (work / "worker-result.json").open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False, allow_nan=False)
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
