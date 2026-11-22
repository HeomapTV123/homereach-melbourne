"""Test fixed fictional GTFS service-day boundaries with the reviewed R5 engine."""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

if __name__ == "__main__":
    sys.dont_write_bytecode = True

import check_routing_runtime as runtime
import routing_service_day_fixture as fixture
import routing_walk_geometry as geometry
import run_routing_smoke_test as smoke


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "scripts" / "_routing_service_day_worker.py"
TIMEOUT_SECONDS = 180
REPORT_LIMIT_BYTES = 2_000_000
SOURCE_PATHS = (
    "scripts/run_routing_service_day_test.py", "scripts/_routing_service_day_worker.py",
    "scripts/routing_service_day_fixture.py", "scripts/run_routing_smoke_test.py",
    "scripts/_routing_smoke_worker.py", "scripts/routing_smoke_fixture.py",
    "scripts/routing_walk_geometry.py", "scripts/routing_leg_isolation.py",
    "scripts/routing_street_index_correction.py", "scripts/routing_street_origin_correction.py",
    "scripts/routing_street_geometry_correction.py", "scripts/routing_native/HomeReachStreetOrigins.java",
    "scripts/check_routing_runtime.py",
)


def _source_hashes() -> dict:
    import hashlib
    return {relative: hashlib.sha256((ROOT / relative).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for relative in SOURCE_PATHS}


def validate_result(report: dict) -> list[str]:
    """Require all controls and date-specific BUS outcomes; never alter returned rows."""
    problems = []
    if report.get("status") != "completed":
        problems.append(str(report.get("error", "Worker did not complete the service-day experiment.")))
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
    if type(report.get("queries_attempted")) is not int or report["queries_attempted"] != len(fixture.CASES):
        problems.append("Not all service-day queries were attempted.")
    if type(report.get("walking_queries_attempted")) is not int or report["walking_queries_attempted"] != 1:
        problems.append("The independent walking control was not executed.")
    problems.extend(smoke.validate_integration(report, True))
    problems.extend(smoke.validate_walking_correction(report, True))
    observations = report.get("queries")
    if not isinstance(observations, list) or len(observations) != len(fixture.CASES):
        problems.append("Missing or extra query observations.")
    if not isinstance(observations, list):
        observations = []
    checks = []
    for index, case in enumerate(fixture.CASES):
        local_problems = []
        observed = observations[index] if index < len(observations) else None
        if not isinstance(observed, dict):
            local_problems.append("Missing or malformed observation.")
            observed = {}
        identity = {"id": case["id"], "departure": case["departure"],
                    "departure_time_window_seconds": fixture.QUERY_WINDOW_SECONDS,
                    "max_time_seconds": 1200, "transport_modes": ["BUS"]}
        if any(observed.get(key) != value or type(observed.get(key)) is not type(value)
               for key, value in identity.items()):
            local_problems.append("Query settings differ from the fixed case.")
        if observed.get("error"):
            local_problems.append(str(observed["error"]))
        check = fixture.validate_case(case, observed.get("rows"))
        check["id"] = case["id"]
        if isinstance(observed.get("rows"), list) and observed["rows"]:
            walking_report = {"walking": report.get("walking"), "transit": observed["rows"],
                              "geometry_crs": {"walking": report.get("walking_crs"),
                                               "transit": observed.get("geometry_crs")}}
            walking = geometry.audit_walk_geometry(walking_report)
            durations = smoke.walking_duration_diagnostics(walking_report)
            check["walking_geometry"] = walking
            check["walking_durations"] = durations
            local_problems.extend(walking["problems"] + durations["problems"])
        check["problem_count"] += len(local_problems)
        check["problems"] = (local_problems + check["problems"])[:fixture.MAX_PROBLEM_EXAMPLES]
        if check["problem_count"]:
            check["status"] = "failed"
        checks.append(check)
        problems.extend(f"{case['id']}: {problem}" for problem in check["problems"])
    report["case_diagnostics"] = checks
    report["positive_cases_passed"] = sum(c["status"] == "passed" for case, c in zip(fixture.CASES, checks)
                                          if case["expected_route_id"] is not None)
    report["negative_cases_passed"] = sum(c["status"] == "passed" for case, c in zip(fixture.CASES, checks)
                                          if case["expected_route_id"] is None)
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


def inspect_service_days(jar: Path, work_root: Path) -> dict:
    started = time.monotonic()
    report = {"schema_version": 1, "stage": "synthetic_service_day_compatibility",
              "status": "blocked", "synthetic_fixture_only": True,
              "requested_itinerary_mode": "isolated_legs",
              "fixed_fixture_walking_correction": True,
              "real_project_datasets_read": 0, "melbourne_journeys_computed": 0,
              "routing_ready": False, "temporary_workspace_created": False,
              "temporary_workspace_removed": True, "protected_inputs_unchanged": None,
              "problems": [], "cases": list(fixture.CASES),
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
        with tempfile.TemporaryDirectory(prefix="homereach-service-day-", dir=work_root) as directory:
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
            # The parent owns scope, provenance and cleanup statements. A worker
            # result cannot replace those facts, even if its itineraries pass.
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
    parser.add_argument("--json", action="store_true", help="Print complete observations and diagnostics.")
    args = parser.parse_args(argv)
    report = inspect_service_days(args.jar, args.work_root)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
    else:
        print("SYNTHETIC SERVICE-DAY COMPATIBILITY:", report["status"].upper())
        print("Fictional Melbourne-timezone timetable | Fixed-fixture walking corrections enabled")
        for check in report.get("case_diagnostics", []):
            print(f"{check['id']}: {check['status']} | options checked: {check['options_checked']}")
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
