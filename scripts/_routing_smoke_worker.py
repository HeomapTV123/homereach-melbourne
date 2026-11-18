"""Internal fresh-process worker for the fixed synthetic routing experiment."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import datetime
import json
import os
from pathlib import Path
import sys
import traceback
import warnings

# The parent uses isolated Python mode. Only this checkout's fixed scripts
# directory is added, so no working-directory Python module is imported.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import routing_smoke_fixture as fixture
from routing_leg_isolation import isolate_cached_legs
import run_routing_smoke_test as smoke


def records(frame) -> list[dict]:
    result = []
    for _, row in frame.iterrows():
        def optional_id(name):
            value = row.get(name)
            return value if isinstance(value, str) else None

        result.append({
            "from_id": str(row["from_id"]), "to_id": str(row["to_id"]),
            "option": int(row["option"]), "segment": int(row["segment"]),
            "mode": row["transport_mode"].name,
            "departure_time": row["departure_time"].isoformat(),
            "travel_time_seconds": float(row["travel_time"].total_seconds()),
            "wait_time_seconds": float(row["wait_time"].total_seconds()),
            "distance_m": float(row["distance"]),
            "geometry_nonempty": row.geometry is not None and not row.geometry.is_empty,
            "agency_id": optional_id("agency_id"), "route_id": optional_id("route_id"),
            "start_stop_id": optional_id("start_stop_id"), "end_stop_id": optional_id("end_stop_id"),
        })
    return result


def execute(work: Path, report: dict, *, isolate_legs: bool = False) -> None:
    jar = work / smoke.ENGINE_NAME
    smoke.check_engine(jar)
    if smoke.sha256(work / "streets.osm.pbf") != smoke.STREET_SHA256:
        raise ValueError("Worker street fixture fingerprint mismatch.")
    # Refuse incidental Python writes outside this run, including r5py's global
    # /etc template attempt. Java/native IO is not sandboxed by Python hooks.
    sys.addaudithook(smoke.python_write_guard(work))
    import configargparse

    # Pinned r5py reuses this default public singleton when already initialised.
    # Its global/user default config files must not change this fixed experiment.
    configargparse.get_argument_parser(prog="r5py", default_config_files=[])
    sys.argv = [sys.argv[0], "--r5-classpath", str(jar), "--max-memory", "1G",
                "--temporary-directory", str(work / "tmp")]
    import r5py
    import geopandas as gpd
    import jpype
    import rasterio  # Exercise this installed native dependency as well.
    from shapely.geometry import Point
    from r5py.util.config import Config
    import java.lang

    r5py.DetailedItineraries.NUM_THREADS = 1
    classpath = str(java.lang.System.getProperty("java.class.path"))
    entries = [Path(p).resolve() for p in classpath.split(os.pathsep)]
    temp_directory = Path(str(java.lang.System.getProperty("java.io.tmpdir"))).resolve()
    report["engine"] = {
        "r5py": r5py.__version__, "sha256": smoke.sha256(jar),
        "jvm_started": jpype.isJVMStarted(), "java_version": str(java.lang.System.getProperty("java.version")),
        "max_heap_bytes": int(java.lang.Runtime.getRuntime().maxMemory()),
        "classpath_verified": jar.resolve() in entries,
        "temporary_directory_verified": temp_directory.is_relative_to(work / "tmp"),
        "python_routing_jobs": r5py.DetailedItineraries.NUM_THREADS,
        "rasterio_imported": rasterio.__version__,
        "default_configuration_files": [],
        "python_guard_scope": "Python file mutations and socket operations; not a Java/native sandbox",
    }
    if Path(Config().arguments.r5_classpath).resolve() != jar.resolve():
        raise ValueError("r5py selected a different classpath.")
    network = r5py.TransportNetwork(work / "streets.osm.pbf", [work / "synthetic.gtfs.zip"], allow_errors=False)
    origins = gpd.GeoDataFrame({"id": [smoke.ORIGIN_ID]}, geometry=[Point(*fixture.ORIGIN)], crs="EPSG:4326")
    destinations = gpd.GeoDataFrame({"id": [smoke.DESTINATION_ID]}, geometry=[Point(*fixture.DESTINATION)], crs="EPSG:4326")
    context = isolate_cached_legs(r5py) if isolate_legs else nullcontext()
    with context as adapter:
        if isolate_legs:
            report["itinerary_adapter"] = adapter
        for label, departure, mode in (
            ("walking", fixture.ACTIVE_DEPARTURE, r5py.TransportMode.WALK),
            ("transit", fixture.ACTIVE_DEPARTURE, r5py.TransportMode.BUS),
            ("no_service", fixture.INACTIVE_DEPARTURE, r5py.TransportMode.BUS),
        ):
            report["queries_attempted"] += 1
            frame = r5py.DetailedItineraries(
                network, origins=origins, destinations=destinations,
                departure=departure, departure_time_window=datetime.timedelta(minutes=10),
                transport_modes=[mode], access_modes=[r5py.TransportMode.WALK],
                egress_modes=[r5py.TransportMode.WALK], snap_to_network=False,
                max_time=datetime.timedelta(minutes=90), max_time_walking=datetime.timedelta(minutes=90),
                max_public_transport_rides=1, speed_walking=3.6,
            )
            report[label] = records(frame)
    report["status"] = "completed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--isolate-itinerary-legs", action="store_true")
    args = parser.parse_args()
    work = Path.cwd().resolve()
    # Parent creates the run directory; direct invocation from a checkout is invalid.
    if not work.name.startswith("homereach-smoke-") or work.is_relative_to(smoke.ROOT):
        raise ValueError("Run this worker through run_routing_smoke_test.py.")
    report = {"status": "failed", "queries_attempted": 0,
              "itinerary_mode": "isolated_legs" if args.isolate_itinerary_legs else "upstream"}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            execute(work, report, isolate_legs=args.isolate_itinerary_legs)
        except Exception as error:
            report["error"] = f"{type(error).__name__}: {error}"
            traceback.print_exc()
        report["warnings"] = sorted({str(w.message) for w in caught})
    with (work / "worker-result.json").open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False, allow_nan=False)
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
