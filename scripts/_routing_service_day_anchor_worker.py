"""Fresh native worker for the fixed service-date anchor counterfactual.

Only the existing synthetic fixture is loaded. Transit state chains are retained
as native integer fields: this worker never invokes TripPlanner.transit_paths.
"""
from __future__ import annotations

from contextlib import ExitStack
import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback
import warnings

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _routing_service_day_worker import verify_inputs
from _routing_smoke_worker import records
import routing_service_day_anchor as anchor
import routing_service_day_fixture as fixture
import routing_smoke_fixture as street_fixture
from routing_street_geometry_correction import correct_street_geometries
from routing_street_index_correction import correct_fixture_index
from routing_street_origin_correction import correct_street_origins
import run_routing_smoke_test as smoke


REQUEST_SOURCE_SHA256 = {
    "r5/regional_task.py": "2cb5729eb461fc66d7e482f833373121e87e8b21cc68f81f46cc4d5ea8be6876",
    "r5/trip_planner.py": "541bcf3ec644bb717195518699ad540d1c448330539e26b1f36cd850ff7674a7",
}


def native_request_fields(request) -> dict:
    """Capture native fields without accessing the Python departure serializer."""
    return {
        "native_date": str(request.date), "from_time": int(request.fromTime),
        "to_time": int(request.toTime), "from_lon": float(request.fromLon),
        "from_lat": float(request.fromLat), "to_lon": float(request.toLon),
        "to_lat": float(request.toLat), "monte_carlo_draws": int(request.monteCarloDraws),
        "max_trip_duration_minutes": int(request.maxTripDurationMinutes),
        "max_rides": int(request.maxRides), "suboptimal_minutes": int(request.suboptimalMinutes),
        "walk_speed_mps": float(request.walkSpeed), "reverse_search": bool(request.reverseSearch),
        "transit_modes": sorted(str(mode) for mode in request.transitModes),
        "access_modes": sorted(str(mode) for mode in request.accessModes),
        "egress_modes": sorted(str(mode) for mode in request.egressModes),
    }


def native_catalog(transit) -> dict:
    stops = [{"stop_index": i, "scoped_stop_id": str(value),
              "stop_id": str(value).split(":")[-1]}
             for i, value in enumerate(transit.stopIdForIndex)]
    services = [{"service_code": i, "service_id": str(service.service_id)}
                for i, service in enumerate(transit.services)]
    schedules = []
    for p_index, pattern in enumerate(transit.tripPatterns):
        route = transit.routes.get(pattern.routeIndex)
        stop_indices = [int(i) for i in pattern.stops]
        for t_index, schedule in enumerate(pattern.tripSchedules):
            schedules.append({
                "pattern_index": p_index, "trip_index": t_index,
                "route_id": str(route.route_id), "scoped_trip_id": str(schedule.tripId),
                "trip_id": str(schedule.tripId).split(":")[-1],
                "service_code": int(schedule.serviceCode), "stop_indices": stop_indices,
                "stop_ids": [stops[i]["stop_id"] for i in stop_indices],
                "arrivals": [int(s) for s in schedule.arrivals],
                "departures": [int(s) for s in schedule.departures],
                "frequency_based": schedule.headwaySeconds is not None,
            })
    return {"stops": stops, "services": services, "schedules": schedules}


def native_costs(access, egress, transit) -> dict:
    result = {}
    for role, mapping in (("access", access), ("egress", egress)):
        rows = []
        for entry in mapping.entrySet():
            mode, stops = str(entry.getKey()), entry.getValue()
            for index in sorted(int(i) for i in stops.keys()):
                rows.append({"mode": mode, "stop_index": index,
                             "stop_id": str(transit.stopIdForIndex.get(index)).split(":")[-1],
                             "seconds": int(stops.get(index))})
        result[role] = sorted(rows, key=lambda row: (row["mode"], row["stop_index"]))
    return result


def native_state_chain(final_state) -> list[dict]:
    """Snapshot each complete native back-pointer chain immediately after routing."""
    chain, state = [], final_state
    while state is not None:
        if len(chain) >= 10:
            raise ValueError("Native path exceeds the fixed single-ride state bound.")
        chain.append({
            "time": int(state.time), "board_time": int(state.boardTime),
            "pattern": int(state.pattern), "trip": int(state.trip),
            "round": int(state.round), "stop": int(state.stop),
            "board_stop_position": int(state.boardStopPosition),
            "alight_stop_position": int(state.alightStopPosition),
            "access_mode": None if state.accessMode is None else str(state.accessMode),
            "egress_mode": None if state.egressMode is None else str(state.egressMode),
        })
        state = state.back
    return list(reversed(chain))


def active_service_bits(router, count: int) -> list[int]:
    """Read the router's actual selected bitset; never change engine internals."""
    field = router.getClass().getDeclaredField("servicesActive")
    field.setAccessible(True)
    active = field.get(router)
    if active.length() > count:
        raise ValueError("Router active-service bitset extends beyond the native catalog.")
    return [i for i in range(count) if active.get(i)]


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
    from r5py.r5.trip_planner import TripPlanner
    from r5py.util.config import Config

    package = Path(r5py.__file__).resolve().parent
    hashes = {name: hashlib.sha256((package / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
              for name in REQUEST_SOURCE_SHA256}
    if r5py.__version__ != "1.1.7" or hashes != REQUEST_SOURCE_SHA256:
        raise ValueError("Native anchor probe requires the reviewed r5py request/planner sources.")
    report["request_source_sha256"] = hashes
    r5py.DetailedItineraries.NUM_THREADS = 1
    if Path(Config().arguments.r5_classpath).resolve() != jar.resolve():
        raise ValueError("r5py selected a different classpath.")
    system = jpype.JClass("java.lang.System")
    report["engine"] = {
        "r5py": r5py.__version__, "sha256": smoke.sha256(jar),
        "jvm_started": jpype.isJVMStarted(),
        "java_version": str(system.getProperty("java.version")),
        "max_heap_bytes": int(jpype.JClass("java.lang.Runtime").getRuntime().maxMemory()),
        "classpath_verified": jar.resolve() in [Path(p).resolve() for p in
            str(system.getProperty("java.class.path")).split(os.pathsep)],
        "temporary_directory_verified": Path(str(system.getProperty("java.io.tmpdir"))).resolve().is_relative_to(work / "tmp"),
        "python_routing_jobs": 1, "rasterio_imported": rasterio.__version__,
        "default_configuration_files": [],
        "python_guard_scope": "Python file mutations and socket operations; not a Java/native sandbox",
    }
    network = r5py.TransportNetwork(work / "streets.osm.pbf", [work / "service-day.gtfs.zip"], allow_errors=False)
    report["engine"]["network_timezone"] = str(network.timezone)
    if str(network.timezone) != fixture.TIMEZONE:
        raise ValueError("The native network timezone differs from the reviewed fixture.")
    transit = network.transit_layer._transit_layer
    report.update(native_catalog(transit))
    origins = gpd.GeoDataFrame({"id": [smoke.ORIGIN_ID]}, geometry=[Point(*fixture.ORIGIN)], crs="EPSG:4326")
    destinations = gpd.GeoDataFrame({"id": [smoke.DESTINATION_ID]}, geometry=[Point(*fixture.DESTINATION)], crs="EPSG:4326")
    NativeRouter = jpype.JClass("com.conveyal.r5.profile.McRaptorSuboptimalPathProfileRouter")
    DominatingList = jpype.JClass("com.conveyal.r5.profile.SuboptimalDominatingList")
    LocalDate = jpype.JClass("java.time.LocalDate")
    with ExitStack() as contexts:
        correction = report["walking_correction"] = {}
        correction["index"] = contexts.enter_context(correct_fixture_index(network, street_fixture))
        correction["origin"] = contexts.enter_context(correct_street_origins(r5py, work, jar))
        correction["geometry"] = contexts.enter_context(correct_street_geometries(r5py))
        report["walking_queries_attempted"] = 1
        walking = r5py.DetailedItineraries(
            network, origins=origins, destinations=destinations,
            departure=datetime.datetime(2026, 10, 13, 8),
            departure_time_window=datetime.timedelta(seconds=anchor.WINDOW_SECONDS),
            transport_modes=[r5py.TransportMode.WALK], snap_to_network=False,
            max_time=datetime.timedelta(minutes=90), max_time_walking=datetime.timedelta(minutes=90),
            max_public_transport_rides=1, speed_walking=smoke.WALK_SPEED_KMH,
        )
        report["walking"] = records(walking, include_geometry=True)
        report["walking_crs"] = str(walking.crs)
        for pair in anchor.PAIRS:
            observed = {"id": pair["id"], "civil_departure": pair["civil_departure"], "arms": []}
            report["pairs"].append(observed)
            try:
                request = RegionalTask(
                    network, origin=Point(*fixture.ORIGIN), destinations=destinations,
                    departure=datetime.datetime.fromisoformat(pair["civil_departure"]),
                    departure_time_window=datetime.timedelta(seconds=anchor.WINDOW_SECONDS),
                    transport_modes=[r5py.TransportMode.BUS], access_modes=[r5py.TransportMode.WALK],
                    egress_modes=[r5py.TransportMode.WALK], max_time=datetime.timedelta(minutes=20),
                    max_time_walking=datetime.timedelta(minutes=20), max_public_transport_rides=1,
                    speed_walking=smoke.WALK_SPEED_KMH,
                )
                request._regional_task.toLon, request._regional_task.toLat = fixture.DESTINATION
                observed["base_request"] = native_request_fields(request._regional_task)
                # Only walking costs are obtained from TripPlanner. Its transit
                # serializer assumes Python request midnight and is never called.
                planner = TripPlanner(network, request)
                access, egress = planner._transit_access_times, planner._transit_egress_times
                observed["costs_before"] = native_costs(access, egress, transit)
                for name in anchor.ARMS:
                    arm = {"name": name}
                    observed["arms"].append(arm)
                    report["queries_attempted"] += 1
                    try:
                        native = request._regional_task.clone()
                        spec = anchor.request_spec(pair, name)
                        native.date = LocalDate.parse(spec["native_date"])
                        native.fromTime, native.toTime = spec["from_time"], spec["to_time"]
                        arm["request"] = native_request_fields(native)
                        arm["costs_before"] = native_costs(access, egress, transit)

                        def list_supplier(_departure):
                            return DominatingList(max(int(native.suboptimalMinutes), 0))

                        router = NativeRouter(network._transport_network, native, access, egress,
                                              list_supplier, None, True)
                        arm["active_services"] = active_service_bits(router, len(report["services"]))
                        router.route()
                        arm["request_after"] = native_request_fields(native)
                        arm["costs_after"] = native_costs(access, egress, transit)
                        samples = router.finalStatesByDepartureTime
                        keys = sorted(int(k) for k in samples.keys())
                        if len(keys) > anchor.MAX_SAMPLES:
                            raise ValueError("Native sample count exceeds the fixed request bound.")
                        arm["samples"] = []
                        for key in keys:
                            paths = list(samples.get(key))
                            if len(paths) > 10:
                                raise ValueError("Native sample exceeds the fixed path bound.")
                            arm["samples"].append({
                                "departure_seconds": key,
                                "derived_civil_departure": anchor.civil_time(spec["native_date"], key),
                                "chains": [native_state_chain(state) for state in paths],
                            })
                    except Exception as error:
                        arm["error"] = f"{type(error).__name__}: {error}"
                        traceback.print_exc()
                observed["base_request_after"] = native_request_fields(request._regional_task)
                observed["costs_after"] = native_costs(access, egress, transit)
            except Exception as error:
                observed["error"] = f"{type(error).__name__}: {error}"
                traceback.print_exc()
    report.update({key + "_after": value for key, value in native_catalog(transit).items()})
    report["status"] = "completed"


def main() -> int:
    work = Path.cwd().resolve()
    if not work.name.startswith("homereach-service-day-anchor-") or work.is_relative_to(smoke.ROOT):
        raise ValueError("Run this worker through run_routing_service_day_anchor_test.py.")
    report = {"status": "failed", "queries_attempted": 0, "walking_queries_attempted": 0,
              "pairs": [], "transit_itinerary_serialization_used": False,
              "native_transit_router_modified": False}
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
