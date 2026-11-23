"""Compare native service-date anchors on an unchanged fictional timetable."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

if __name__ == "__main__":
    sys.dont_write_bytecode = True

import check_routing_runtime as runtime
import routing_service_day_anchor as anchor
import routing_service_day_fixture as fixture
import routing_walk_geometry as geometry
import run_routing_smoke_test as smoke


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "scripts" / "_routing_service_day_anchor_worker.py"
TIMEOUT_SECONDS = 180
REPORT_LIMIT_BYTES = 8_000_000
REQUEST_SOURCE_SHA256 = {
    "r5/regional_task.py": "2cb5729eb461fc66d7e482f833373121e87e8b21cc68f81f46cc4d5ea8be6876",
    "r5/trip_planner.py": "541bcf3ec644bb717195518699ad540d1c448330539e26b1f36cd850ff7674a7",
}
SOURCE_PATHS = (
    "scripts/run_routing_service_day_anchor_test.py",
    "scripts/_routing_service_day_anchor_worker.py",
    "scripts/routing_service_day_anchor.py",
    "scripts/routing_service_day_fixture.py", "scripts/_routing_service_day_worker.py",
    "scripts/run_routing_smoke_test.py", "scripts/_routing_smoke_worker.py",
    "scripts/routing_smoke_fixture.py", "scripts/routing_walk_geometry.py",
    "scripts/routing_leg_isolation.py", "scripts/routing_street_index_correction.py",
    "scripts/routing_street_origin_correction.py", "scripts/routing_street_geometry_correction.py",
    "scripts/routing_native/HomeReachStreetOrigins.java", "scripts/check_routing_runtime.py",
)


def _source_hashes() -> dict:
    return {relative: hashlib.sha256((ROOT / relative).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for relative in SOURCE_PATHS}


def _validate_direct_walk(row: dict) -> list[str]:
    """Check the direct control against the fixed independent street reference."""
    problems = []
    try:
        references, _ = geometry.reference_walks()
        reference = references["direct"]
        shape = row.get("geometry")
        if not isinstance(shape, dict) or shape.get("type") != "LineString":
            raise ValueError("Expected a LineString for the independent walking control.")
        points = shape.get("coordinates")
        if not isinstance(points, list) or len(points) < 2:
            raise ValueError("Independent walking geometry requires at least two points.")
        for point in points:
            if (not isinstance(point, list) or len(point) != 2
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in point)
                    or not -180 <= point[0] <= 180 or not -90 <= point[1] <= 90):
                raise ValueError("Independent walking geometry has invalid coordinates.")
        start, end = reference["start"], reference["end"]
        endpoint_error = min(
            max(geometry.haversine_m(points[0], start), geometry.haversine_m(points[-1], end)),
            max(geometry.haversine_m(points[0], end), geometry.haversine_m(points[-1], start)),
        )
        if endpoint_error > geometry.ENDPOINT_TOLERANCE_M:
            problems.append("Independent walking geometry endpoints differ from the reference.")
        low, high = sorted((start[0], end[0]))
        if any(geometry.haversine_m(p, (min(high, max(low, p[0])), start[1]))
               > geometry.ENDPOINT_TOLERANCE_M for p in points):
            problems.append("Independent walking geometry leaves the reference path.")
        length = sum(geometry.haversine_m(a, b) for a, b in zip(points, points[1:]))
        distance = row.get("distance_m")
        if type(distance) not in (int, float) or not math.isfinite(distance) or distance <= 0:
            raise ValueError("Independent walking distance must be positive and finite.")
        if (abs(length - distance) > reference["length_tolerance_m"]
                or abs(distance - reference["distance_m"]) > reference["length_tolerance_m"]):
            problems.append("Independent walking geometry or distance differs from the reference length.")
    except (TypeError, ValueError, KeyError, OSError, OverflowError) as error:
        problems.append(str(error))
    return problems


def validate_result(report: dict) -> list[str]:
    """Validate the causal probe; success never clears the compatibility gate."""
    problems = []
    if report.get("status") != "completed":
        problems.append(str(report.get("error", "Worker did not complete the native anchor experiment.")))
    if (report.get("transit_itinerary_serialization_used") is not False
            or report.get("native_transit_router_modified") is not False):
        problems.append("Native-only observation and unchanged transit router scope were not verified.")
    if report.get("request_source_sha256") != REQUEST_SOURCE_SHA256:
        problems.append("The pinned request and planner source fingerprints were not verified.")
    engine = report.get("engine")
    if not isinstance(engine, dict):
        problems.append("Missing engine identity.")
        engine = {}
    expected = {"r5py": runtime.BASELINE_R5PY, "sha256": smoke.ENGINE_SHA256,
                "jvm_started": True, "classpath_verified": True,
                "temporary_directory_verified": True, "python_routing_jobs": 1,
                "network_timezone": fixture.TIMEZONE, "default_configuration_files": []}
    if any(engine.get(key) != value or type(engine.get(key)) is not type(value)
           for key, value in expected.items()):
        problems.append("Engine identity, isolation, timezone or execution settings were not verified.")
    if not isinstance(engine.get("java_version"), str) or not engine["java_version"].startswith("21."):
        problems.append("Embedded JVM is not the reviewed Java 21 baseline.")
    heap = engine.get("max_heap_bytes")
    if type(heap) is not int or not 0 < heap <= smoke.HEAP_BYTES:
        problems.append("Embedded Java heap was not bounded to 1 GiB.")
    if type(report.get("queries_attempted")) is not int or report["queries_attempted"] != 2 * len(anchor.PAIRS):
        problems.append("Not all paired native queries were attempted.")
    if type(report.get("walking_queries_attempted")) is not int or report["walking_queries_attempted"] != 1:
        problems.append("The independent walking control was not executed.")
    problems.extend(smoke.validate_walking_correction(report, True))
    walks = report.get("walking")
    if (not isinstance(walks, list) or len(walks) != 1 or not isinstance(walks[0], dict)
            or report.get("walking_crs") != "EPSG:4326"):
        problems.append("Missing or malformed independent walking control.")
    else:
        row = walks[0]
        identity = {"from_id": smoke.ORIGIN_ID, "to_id": smoke.DESTINATION_ID,
                    "option": 0, "segment": 0, "mode": "WALK", "geometry_nonempty": True}
        if any(row.get(k) != v or type(row.get(k)) is not type(v) for k, v in identity.items()):
            problems.append("Independent walking control identity differs from the fixture.")
        problems.extend(_validate_direct_walk(row))
        durations = smoke.walking_duration_diagnostics({"walking": walks, "transit": []})
        report["walking_duration_diagnostics"] = durations
        problems.extend(durations["problems"])
    problems.extend(anchor.validate_pairs(report))
    return sorted(set(problems))


def run_worker(work: Path) -> dict:
    log_path = work / "worker.log"
    with log_path.open("xb") as log:
        try:
            completed = subprocess.run(
                [sys.executable, "-I", "-B", str(WORKER)], cwd=work,
                env=smoke.child_environment(work), stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, shell=False, check=False,
                timeout=TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return {"status": "failed", "problems": [f"Worker exceeded {TIMEOUT_SECONDS} seconds."],
                    "worker_log_tail": smoke.read_log_tail(log_path)}
    report = {}
    try:
        path = work / "worker-result.json"
        if path.stat().st_size > REPORT_LIMIT_BYTES:
            raise ValueError("Worker report exceeds the fixed experiment limit.")
        report = json.loads(path.read_text(encoding="utf-8"), parse_constant=smoke.finite_json_number,
                            parse_float=smoke.finite_json_number)
        if not isinstance(report, dict):
            raise ValueError("Worker report must be an object.")
        problems = validate_result(report)
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as error:
        report = {}
        problems = [f"Cannot validate worker report: {error}"]
    if completed.returncode:
        problems.append(f"Worker exited with code {completed.returncode}.")
    report.update(status="failed" if problems else "passed", problems=problems)
    if problems:
        report["worker_log_tail"] = smoke.read_log_tail(log_path)
    return report


def inspect_service_day_anchors(jar: Path, work_root: Path) -> dict:
    started = time.monotonic()
    report = {"schema_version": 1, "stage": "synthetic_service_day_anchor_probe",
              "status": "blocked", "synthetic_fixture_only": True,
              "native_state_diagnostic_only": True, "production_correction": False,
              "fixed_fixture_walking_correction": True,
              "real_project_datasets_read": 0, "melbourne_journeys_computed": 0,
              "routing_ready": False, "temporary_workspace_created": False,
              "temporary_workspace_removed": True, "protected_inputs_unchanged": None,
              "problems": [], "pair_cases": list(anchor.PAIRS),
              "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    inventory = runtime.inspect_runtime()
    report["runtime_inventory"] = inventory
    if inventory["blockers"]:
        report["problems"] = inventory["blockers"]
        return report
    protected = {}
    sources = None
    work = None
    try:
        jar = jar.resolve()
        smoke.check_engine(jar)
        work_root = smoke.check_work_root(work_root)
        if smoke.sha256(smoke.STREET_FIXTURE) != smoke.STREET_SHA256:
            raise ValueError("Reviewed street fixture fingerprint mismatch.")
        protected = {jar: smoke.sha256(jar), smoke.STREET_FIXTURE: smoke.STREET_SHA256}
        sources = _source_hashes()
        report["execution_source_sha256"] = sources
        with tempfile.TemporaryDirectory(prefix="homereach-service-day-anchor-", dir=work_root) as directory:
            work = Path(directory).resolve()
            report["temporary_workspace_created"] = True
            for name in ("config", "cache", "tmp"):
                (work / name).mkdir()
            shutil.copyfile(jar, work / smoke.ENGINE_NAME)
            smoke.check_engine(work / smoke.ENGINE_NAME)
            shutil.copyfile(smoke.STREET_FIXTURE, work / "streets.osm.pbf")
            fixture.write_gtfs(work / "service-day.gtfs.zip")
            fixture_hashes = {name: smoke.sha256(work / name) for name in
                              (smoke.ENGINE_NAME, "streets.osm.pbf", "service-day.gtfs.zip")}
            report["fixture_sha256"] = fixture_hashes
            worker_report = run_worker(work)
            reserved = set(report) - {"status", "problems"}
            conflicts = sorted(reserved.intersection(worker_report))
            report.update({key: value for key, value in worker_report.items() if key not in reserved})
            if conflicts:
                report["status"] = "failed"
                report["problems"].append("Worker attempted to replace parent metadata: " + ", ".join(conflicts))
            if any(smoke.sha256(work / name) != digest for name, digest in fixture_hashes.items()):
                report["status"] = "failed"
                report["problems"].append("A staged input changed during the experiment.")
    except (OSError, ValueError) as error:
        report["status"] = "failed" if report["temporary_workspace_created"] else "blocked"
        report["problems"].append(str(error))
    finally:
        if work is not None:
            report["temporary_workspace_removed"] = not work.exists()
            if not report["temporary_workspace_removed"]:
                report["status"] = "failed"
                report["problems"].append("Temporary workspace cleanup did not complete.")
        if protected:
            try:
                unchanged = all(smoke.sha256(path) == digest for path, digest in protected.items())
                unchanged = unchanged and _source_hashes() == sources
                report["protected_inputs_unchanged"] = unchanged
                if not unchanged:
                    report["status"] = "failed"
                    report["problems"].append("An original input or execution source changed.")
            except OSError as error:
                report["status"] = "failed"
                report["problems"].append(f"Cannot recheck original inputs: {error}")
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", required=True, type=Path, help="Existing reviewed local R5 JAR.")
    parser.add_argument("--work-root", required=True, type=Path, help="Existing temporary directory outside checkout.")
    parser.add_argument("--json", action="store_true", help="Print complete native observations and diagnostics.")
    args = parser.parse_args(argv)
    report = inspect_service_day_anchors(args.jar, args.work_root)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
    else:
        print("SYNTHETIC SERVICE-DAY ANCHOR PROBE:", report["status"].upper())
        print("Paired native states | Fixed fictional timetable | Production correction: False")
        for check in report.get("pair_diagnostics", []):
            print(f"{check['id']}: {check['status']}")
        for problem in report["problems"][:12]:
            print("Detail:", problem)
        if len(report["problems"]) > 12:
            print("Additional problems:", len(report["problems"]) - 12, "| Use --json for the full report.")
        print("Protected inputs unchanged:", report["protected_inputs_unchanged"])
        print("Temporary workspace removed:", report["temporary_workspace_removed"])
        print("Real project datasets read: 0 | Melbourne journeys computed: 0 | Routing ready: False")
    return {"passed": 0, "blocked": 2}.get(report["status"], 1)


if __name__ == "__main__":
    raise SystemExit(main())
