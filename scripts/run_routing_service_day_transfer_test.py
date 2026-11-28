"""Check an uncorrected native two-bus baseline using fictional transit costs.

Eight separate three-stop timetables test mixed service dates, a same-day
positive control, calendar removals and an impossible connection. This is a
transit-only diagnostic: the worker explicitly scopes out interstop walking.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
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
import routing_service_day_transfer as fixture
import run_routing_smoke_test as smoke


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "scripts" / "_routing_service_day_transfer_worker.py"
TIMEOUT_SECONDS = 240
REPORT_LIMIT_BYTES = 8_000_000
REQUEST_SOURCE_SHA256 = {
    "r5/regional_task.py": "2cb5729eb461fc66d7e482f833373121e87e8b21cc68f81f46cc4d5ea8be6876",
    "r5/trip_planner.py": "541bcf3ec644bb717195518699ad540d1c448330539e26b1f36cd850ff7674a7",
}
SOURCE_PATHS = (
    "scripts/run_routing_service_day_transfer_test.py",
    "scripts/_routing_service_day_transfer_worker.py",
    "scripts/routing_service_day_transfer.py",
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


def validate_result(report: dict) -> list[str]:
    """Require native provenance and every control; missing mixed paths fail."""
    problems = []
    if report.get("status") != "completed":
        problems.append(str(report.get("error", "Worker did not complete the native transfer baseline.")))
    scope = {
        "transit_itinerary_serialization_used": False,
        "native_transit_router_modified": False,
        "fixed_artificial_access_egress_costs": True,
        "interstop_transfer_model": "scoped_empty_street_transfers",
        "physical_walking_validated": False,
    }
    if any(report.get(key) != value or type(report.get(key)) is not type(value)
           for key, value in scope.items()):
        problems.append("Native-only algorithm and explicitly artificial transfer-model scope were not verified.")
    if report.get("request_source_sha256") != REQUEST_SOURCE_SHA256:
        problems.append("The pinned request and planner source fingerprints were not verified.")
    engine = report.get("engine")
    if not isinstance(engine, dict):
        problems.append("Missing engine identity.")
        engine = {}
    expected = {"r5py": runtime.BASELINE_R5PY, "sha256": smoke.ENGINE_SHA256,
                "jvm_started": True, "classpath_verified": True,
                "temporary_directory_verified": True, "python_routing_jobs": 1,
                "default_configuration_files": []}
    if any(engine.get(key) != value or type(engine.get(key)) is not type(value)
           for key, value in expected.items()):
        problems.append("Engine identity, isolation or execution settings were not verified.")
    if not isinstance(engine.get("java_version"), str) or not engine["java_version"].startswith("21."):
        problems.append("Embedded JVM is not the reviewed Java 21 baseline.")
    heap = engine.get("max_heap_bytes")
    if type(heap) is not int or not 0 < heap <= smoke.HEAP_BYTES:
        problems.append("Embedded Java heap was not bounded to 1 GiB.")
    for field in ("networks_attempted", "queries_attempted"):
        if type(report.get(field)) is not int or report[field] != len(fixture.CASES):
            problems.append("Not all eight separate networks and native queries were attempted.")
    if type(report.get("walking_queries_attempted")) is not int or report["walking_queries_attempted"] != 0:
        problems.append("The transit-only baseline unexpectedly attempted a walking query.")
    problems.extend(fixture.validate_cases(report))
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


def inspect_service_day_transfers(jar: Path, work_root: Path) -> dict:
    started = time.monotonic()
    report = {"schema_version": 1, "stage": "synthetic_service_day_transfer_baseline",
              "status": "blocked", "synthetic_fixture_only": True,
              "native_state_diagnostic_only": True, "production_correction": False,
              "uncorrected_current_date_baseline": True,
              "date_service_projection_used": False,
              "fixed_fixture_walking_correction": False,
              "transit_only_model": "Artificial 12-second access/egress; no interstop walking",
              "real_project_datasets_read": 0, "melbourne_journeys_computed": 0,
              "routing_ready": False, "temporary_workspace_created": False,
              "temporary_workspace_removed": True, "protected_inputs_unchanged": None,
              "problems": [], "case_definitions": list(fixture.CASES),
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
        with tempfile.TemporaryDirectory(prefix="homereach-service-day-transfer-", dir=work_root) as directory:
            work = Path(directory).resolve()
            report["temporary_workspace_created"] = True
            for name in ("config", "cache", "tmp"):
                (work / name).mkdir()
            shutil.copyfile(jar, work / smoke.ENGINE_NAME)
            smoke.check_engine(work / smoke.ENGINE_NAME)
            shutil.copyfile(smoke.STREET_FIXTURE, work / "streets.osm.pbf")
            names = [smoke.ENGINE_NAME, "streets.osm.pbf"]
            for case in fixture.CASES:
                name = case["id"] + ".gtfs.zip"
                fixture.write_gtfs(work / name, case)
                names.append(name)
            fixture_hashes = {name: smoke.sha256(work / name) for name in names}
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
    report = inspect_service_day_transfers(args.jar, args.work_root)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
    else:
        print("SYNTHETIC SERVICE-DAY TRANSFER BASELINE:", report["status"].upper())
        print("Uncorrected current-date native router | Eight separate fictional three-stop timetables")
        print("Artificial 12-second access/egress | Scoped empty interstop transfers | Physical walking untested")
        for check in report.get("case_diagnostics", []):
            print(f"{check['id']}: {check['status']} | native paths: {check['native_paths_checked']}")
        print("Same-day positive control passed:", report.get("same_day_control_passed", False))
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
