"""Check an uncorrected native two-bus baseline using fictional transit costs.

Eight separate three-stop timetables test mixed service dates, a same-day
positive control, calendar removals and an impossible connection. This is a
transit-only diagnostic: the worker explicitly scopes out interstop walking.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __name__ == "__main__":
    sys.dont_write_bytecode = True

import check_routing_runtime as runtime
import routing_diagnostic_runner as runner
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
    "scripts/routing_diagnostic_runner.py",
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
    return runner.execution_source_hashes(ROOT, SOURCE_PATHS)


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
    return runner.run_worker(work, worker_path=WORKER, timeout_seconds=TIMEOUT_SECONDS,
                             report_limit_bytes=REPORT_LIMIT_BYTES, validator=validate_result)


def _write_fixtures(work: Path) -> tuple[str, ...]:
    names = []
    for case in fixture.CASES:
        name = case["id"] + ".gtfs.zip"
        fixture.write_gtfs(work / name, case)
        names.append(name)
    return tuple(names)


def inspect_service_day_transfers(jar: Path, work_root: Path) -> dict:
    metadata = {"stage": "synthetic_service_day_transfer_baseline",
                "native_state_diagnostic_only": True, "production_correction": False,
                "uncorrected_current_date_baseline": True, "date_service_projection_used": False,
                "fixed_fixture_walking_correction": False,
                "transit_only_model": "Artificial 12-second access/egress; no interstop walking",
                "case_definitions": list(fixture.CASES)}
    return runner.inspect_diagnostic(
        jar, work_root, metadata=metadata, runtime_inventory=runtime.inspect_runtime,
        workspace_prefix="homereach-service-day-transfer-", fixture_writer=_write_fixtures,
        source_hashes=_source_hashes, execute_worker=run_worker,
    )


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
