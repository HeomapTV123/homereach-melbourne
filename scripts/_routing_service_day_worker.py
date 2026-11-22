"""Fresh-process worker for the fixed fictional service-day experiment."""
from __future__ import annotations

import datetime
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import traceback
import warnings
from zipfile import ZipFile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _routing_smoke_worker import records
import routing_service_day_fixture as fixture
import routing_smoke_fixture as street_fixture
from routing_leg_isolation import isolate_cached_legs
from routing_street_geometry_correction import correct_street_geometries
from routing_street_index_correction import correct_fixture_index
from routing_street_origin_correction import correct_street_origins
import run_routing_smoke_test as smoke


def verify_inputs(work: Path) -> None:
    smoke.check_engine(work / smoke.ENGINE_NAME)
    if smoke.sha256(work / "streets.osm.pbf") != smoke.STREET_SHA256:
        raise ValueError("The reviewed street fixture fingerprint changed.")
    expected = fixture.gtfs_tables()
    with ZipFile(work / "service-day.gtfs.zip") as archive:
        if len(archive.namelist()) != len(expected) or set(archive.namelist()) != set(expected):
            raise ValueError("Unexpected synthetic timetable members.")
        if any(archive.read(name) != value for name, value in expected.items()):
            raise ValueError("Synthetic service-day tables differ from the fixed fixture.")


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
    from r5py.util.config import Config
    import java.lang

    r5py.DetailedItineraries.NUM_THREADS = 1
    if Path(Config().arguments.r5_classpath).resolve() != jar.resolve():
        raise ValueError("r5py selected a different classpath.")
    report["engine"] = {
        "r5py": r5py.__version__, "sha256": smoke.sha256(jar),
        "jvm_started": jpype.isJVMStarted(),
        "java_version": str(java.lang.System.getProperty("java.version")),
        "max_heap_bytes": int(java.lang.Runtime.getRuntime().maxMemory()),
        "classpath_verified": jar.resolve() in [Path(p).resolve() for p in
            str(java.lang.System.getProperty("java.class.path")).split(os.pathsep)],
        "temporary_directory_verified": Path(str(java.lang.System.getProperty("java.io.tmpdir"))).resolve().is_relative_to(work / "tmp"),
        "python_routing_jobs": r5py.DetailedItineraries.NUM_THREADS,
        "rasterio_imported": rasterio.__version__, "default_configuration_files": [],
        "python_guard_scope": "Python file mutations and socket operations; not a Java/native sandbox",
    }
    network = r5py.TransportNetwork(work / "streets.osm.pbf", [work / "service-day.gtfs.zip"], allow_errors=False)
    report["engine"]["network_timezone"] = str(network.timezone)
    if str(network.timezone) != fixture.TIMEZONE:
        raise ValueError("Loaded network timezone differs from the fixture agency timezone.")
    origins = gpd.GeoDataFrame({"id": [smoke.ORIGIN_ID]}, geometry=[Point(*fixture.ORIGIN)], crs="EPSG:4326")
    destinations = gpd.GeoDataFrame({"id": [smoke.DESTINATION_ID]}, geometry=[Point(*fixture.DESTINATION)], crs="EPSG:4326")

    def query(departure, mode, max_minutes):
        return r5py.DetailedItineraries(
            network, origins=origins, destinations=destinations,
            departure=departure, departure_time_window=datetime.timedelta(seconds=fixture.QUERY_WINDOW_SECONDS),
            transport_modes=[mode], access_modes=[r5py.TransportMode.WALK],
            egress_modes=[r5py.TransportMode.WALK], snap_to_network=False,
            max_time=datetime.timedelta(minutes=max_minutes), max_time_walking=datetime.timedelta(minutes=max_minutes),
            max_public_transport_rides=1, speed_walking=smoke.WALK_SPEED_KMH,
        )

    with ExitStack() as contexts:
        report["itinerary_adapter"] = contexts.enter_context(isolate_cached_legs(r5py))
        correction = report["walking_correction"] = {}
        correction["index"] = contexts.enter_context(correct_fixture_index(network, street_fixture))
        correction["origin"] = contexts.enter_context(correct_street_origins(r5py, work, jar))
        correction["geometry"] = contexts.enter_context(correct_street_geometries(r5py))
        report["walking_queries_attempted"] = 1
        walking = query(datetime.datetime(2026, 10, 13, 8, 0), r5py.TransportMode.WALK, 90)
        report["walking"] = records(walking, include_geometry=True)
        report["walking_crs"] = str(walking.crs)
        for case in fixture.CASES:
            report["queries_attempted"] += 1
            observation = {"id": case["id"], "departure": case["departure"],
                           "departure_time_window_seconds": fixture.QUERY_WINDOW_SECONDS,
                           "max_time_seconds": 1200, "transport_modes": ["BUS"]}
            try:
                frame = query(datetime.datetime.fromisoformat(case["departure"]), r5py.TransportMode.BUS, 20)
                observation.update(rows=records(frame, include_geometry=True), geometry_crs=str(frame.crs))
            except Exception as error:
                observation["error"] = f"{type(error).__name__}: {error}"
                traceback.print_exc()
            report["queries"].append(observation)
    report["status"] = "completed"


def main() -> int:
    work = Path.cwd().resolve()
    if not work.name.startswith("homereach-service-day-") or work.is_relative_to(smoke.ROOT):
        raise ValueError("Run this worker through run_routing_service_day_test.py.")
    report = {"status": "failed", "queries_attempted": 0, "walking_queries_attempted": 0,
              "queries": [], "itinerary_mode": "isolated_legs"}
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
