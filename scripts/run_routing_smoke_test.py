"""Run a bounded fictional walking/bus test using a verified local R5 engine."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

if __name__ == "__main__":
    sys.dont_write_bytecode = True

import check_routing_runtime as runtime
import routing_smoke_fixture as fixture


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "scripts" / "_routing_smoke_worker.py"
STREET_FIXTURE = ROOT / "tests" / "fixtures" / "routing_smoke" / "streets.osm.pbf"
STREET_SHA256 = "5d8eee5ad473e362142887d9ea41f135d804b6d1fba42576e9a66fc56cf12879"
ENGINE_NAME = "r5-v7.5.1-r5py-all.jar"
ENGINE_URL = "https://github.com/r5py/r5/releases/download/v7.5.1-r5py/" + ENGINE_NAME
ENGINE_SHA256 = "d50be106cadd7b636cfc0e209052767d7df570629f79fdf98ecd5cf5d2d89be7"
ENGINE_BYTES = 64_437_972
HEAP_BYTES = 1_073_741_824
TIMEOUT_SECONDS = 180
ORIGIN_ID = "synthetic_origin"
DESTINATION_ID = "synthetic_destination"


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def check_engine(path: Path) -> None:
    if not path.is_file():
        raise ValueError(f"Local engine JAR is missing: {path}. See docs/commute_routing_smoke_test.md.")
    if path.stat().st_size != ENGINE_BYTES or sha256(path) != ENGINE_SHA256:
        raise ValueError("Engine size/SHA-256 differs from the reviewed R5 release; no engine was loaded.")


def check_work_root(path: Path) -> Path:
    path = path.resolve()
    if not path.is_dir():
        raise ValueError("--work-root must be an existing directory outside the repository.")
    if path.is_relative_to(ROOT):
        raise ValueError("The temporary work directory must be outside the repository.")
    return path


def child_environment(work: Path) -> dict[str, str]:
    excluded = {"JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS", "CLASSPATH",
                "PYTHONPATH", "PYTHONSTARTUP"}
    environment = {k: v for k, v in os.environ.items() if k.upper() not in excluded}
    for name, folder in (("APPDATA", "config"), ("LOCALAPPDATA", "cache"),
                         ("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache"),
                         ("TMPDIR", "tmp"), ("TEMP", "tmp"), ("TMP", "tmp")):
        environment[name] = str(work / folder)
    environment.update(PYTHONDONTWRITEBYTECODE="1", PROJ_NETWORK="OFF",
                       OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    return environment


def python_write_guard(work: Path):
    """Prevent incidental Python writes elsewhere; this is not a native sandbox."""
    work = work.resolve()
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND

    def check(path, dir_fd=None):
        if dir_fd not in (None, -1):
            raise PermissionError("Directory-descriptor writes are outside this smoke-test contract.")
        if isinstance(path, int):
            if path not in (1, 2):
                raise PermissionError("Unexpected writable file descriptor.")
        elif not Path(os.fsdecode(path)).resolve().is_relative_to(work):
            raise PermissionError("Python writes must stay inside the temporary smoke workspace.")

    def audit(event, args):
        if event == "open":
            path, mode, flags = args
            if (mode and any(c in mode for c in "wax+")) or (flags & write_flags):
                check(path)
        elif event in {"os.mkdir", "os.remove", "os.rmdir"}:
            check(args[0], args[-1])
        elif event == "os.truncate":
            check(args[0])
        elif event in {"os.rename", "os.link"}:
            check(args[0], args[2])
            check(args[1], args[3])
        elif event == "os.symlink":
            # Synthetic inputs have no reason to create links.
            raise PermissionError("Link creation is outside this smoke-test contract.")
        elif event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo"}:
            raise PermissionError("The engine smoke worker does not download inputs.")

    return audit


def positive_number(value) -> bool:
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def timeline_diagnostics(rows: list) -> dict:
    """Check each returned option without repairing or dropping inconsistent legs."""
    groups = {}
    malformed = 0
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("option"), int):
            malformed += 1
            continue
        groups.setdefault(row["option"], []).append(row)
    result = {"options_checked": len(groups), "overlaps": 0, "wait_mismatches": 0,
              "malformed_options": malformed, "examples": []}
    for option, legs in groups.items():
        try:
            legs = sorted(legs, key=lambda row: row["segment"])
            if [row["segment"] for row in legs] != list(range(len(legs))):
                raise ValueError("Leg sequence is incomplete or duplicated.")
            departures = [datetime.datetime.fromisoformat(row["departure_time"]) for row in legs]
            for index, row in enumerate(legs):
                if not positive_number(row.get("travel_time_seconds")):
                    raise ValueError("Invalid leg duration.")
                wait = row.get("wait_time_seconds")
                if not isinstance(wait, (int, float)) or not math.isfinite(wait) or wait < 0:
                    raise ValueError("Invalid leg waiting time.")
                if index == 0:
                    continue
                arrival = departures[index - 1] + datetime.timedelta(seconds=legs[index - 1]["travel_time_seconds"])
                gap = (departures[index] - arrival).total_seconds()
                if gap < 0:
                    result["overlaps"] += 1
                    if len(result["examples"]) < 5:
                        result["examples"].append({"option": option, "segment": row["segment"],
                                                   "previous_arrival": arrival.isoformat(),
                                                   "departure": departures[index].isoformat(),
                                                   "overlap_seconds": -gap})
                if row.get("mode") == "BUS" and not math.isclose(wait, gap, abs_tol=1.0):
                    result["wait_mismatches"] += 1
        except (KeyError, TypeError, ValueError, OverflowError):
            result["malformed_options"] += 1
    return result


def validate_outcomes(report: dict) -> list[str]:
    """Check actual legs, not merely a finite matrix value or successful import."""
    problems = []
    if report.get("status") != "completed":
        return [report.get("error", "Worker did not complete all synthetic queries.")]
    if report.get("queries_attempted") != 3:
        problems.append("Expected all three synthetic queries.")
    engine = report.get("engine", {})
    if not isinstance(engine, dict):
        return ["Malformed engine identity report."]
    if engine.get("sha256") != ENGINE_SHA256 or engine.get("r5py") != runtime.BASELINE_R5PY:
        problems.append("The loaded engine identity differs from the reviewed baseline.")
    if engine.get("jvm_started") is not True or engine.get("python_routing_jobs") != 1:
        problems.append("The embedded JVM and single Python routing job were not verified.")
    if not str(engine.get("java_version", "")).startswith("21."):
        problems.append("The embedded JVM differs from the selected Java 21 baseline.")
    if not positive_number(engine.get("max_heap_bytes")) or engine["max_heap_bytes"] > HEAP_BYTES:
        problems.append("The observed Java heap exceeds the selected 1 GiB limit or is unreadable.")
    if engine.get("classpath_verified") is not True or engine.get("temporary_directory_verified") is not True:
        problems.append("The embedded JVM paths were not verified.")
    walking = report.get("walking", [])
    transit = report.get("transit", [])
    no_service = report.get("no_service")
    if not isinstance(walking, list) or not walking:
        problems.append("Walking did not return an itinerary.")
        walking = []
    if not isinstance(transit, list) or not transit:
        problems.append("Active service did not return an itinerary.")
        transit = []
    if no_service != []:
        problems.append("The inactive-date bus-only query unexpectedly returned an itinerary.")
    for label, rows in (("walking", walking), ("transit", transit)):
        for row in rows:
            if not isinstance(row, dict):
                problems.append(f"Malformed {label} leg.")
                continue
            if row.get("from_id") != ORIGIN_ID or row.get("to_id") != DESTINATION_ID:
                problems.append(f"Wrong origin/destination in {label}.")
            if not positive_number(row.get("travel_time_seconds")) or not positive_number(row.get("distance_m")):
                problems.append(f"Nonpositive/nonfinite duration or distance in {label}.")
            if row.get("geometry_nonempty") is not True:
                problems.append(f"Missing geometry in {label}.")
            allowed = {"WALK"} if label == "walking" else {"WALK", "BUS"}
            if row.get("mode") not in allowed:
                problems.append(f"Unexpected mode in {label}.")
    bus_legs = [row for row in transit if isinstance(row, dict) and row.get("mode") == "BUS"]
    if not bus_legs:
        problems.append("No actual BUS leg was returned on the active service date.")
    for row in bus_legs:
        expected = {"agency_id": fixture.AGENCY_ID, "route_id": fixture.ROUTE_ID,
                    "start_stop_id": fixture.START_STOP_ID, "end_stop_id": fixture.END_STOP_ID}
        if any(row.get(key) != value for key, value in expected.items()):
            problems.append("The BUS leg does not use the synthetic route and stops.")
        if row.get("travel_time_seconds") != 300:
            problems.append("The BUS leg differs from the fixture's five-minute timetable.")
        departure = row.get("departure_time", "")
        if departure not in {"2026-10-13T08:05:00", "2026-10-13T08:10:00", "2026-10-13T08:15:00"}:
            problems.append("The BUS departure is absent from the synthetic timetable.")
    timeline = timeline_diagnostics(transit)
    if timeline["overlaps"]:
        problems.append(f"Itinerary chronology failed: {timeline['overlaps']} legs depart before the previous leg arrives.")
    if timeline["wait_mismatches"]:
        problems.append(f"Itinerary waits failed: {timeline['wait_mismatches']} BUS waits disagree with the preceding arrival.")
    if timeline["malformed_options"]:
        problems.append("Some itinerary options have malformed timestamps, durations or segment sequences.")
    return sorted(set(problems))


def finite_json_number(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("Worker report contains a nonfinite number.")
    return value


def read_log_tail(path: Path) -> str:
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - 12_000))
        return handle.read().decode("utf-8", errors="replace")


def run_worker(work: Path) -> dict:
    log_path = work / "worker.log"
    with log_path.open("wb") as log:
        try:
            completed = subprocess.run(
                [sys.executable, "-I", "-B", str(WORKER)], cwd=work, env=child_environment(work),
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                shell=False, check=False, timeout=TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return {"status": "failed", "problems": [f"Engine worker exceeded {TIMEOUT_SECONDS} seconds."],
                    "worker_log_tail": read_log_tail(log_path)}
    report_path = work / "worker-result.json"
    try:
        if report_path.stat().st_size > 1_000_000:
            raise ValueError("Worker report exceeds the smoke-test limit.")
        report = json.loads(report_path.read_text(encoding="utf-8"),
                            parse_constant=finite_json_number, parse_float=finite_json_number)
        if not isinstance(report, dict):
            raise ValueError("Worker report must be a JSON object.")
        problems = validate_outcomes(report)
        if isinstance(report.get("transit"), list):
            report["timeline_diagnostics"] = timeline_diagnostics(report["transit"])
    except (OSError, ValueError, TypeError, KeyError) as error:
        report = {}
        problems = [f"Cannot validate worker report: {error}"]
    if completed.returncode:
        problems.append(f"Engine worker exited with code {completed.returncode}.")
    report.update(status="failed" if problems else "passed", problems=problems)
    if problems:
        report["worker_log_tail"] = read_log_tail(log_path)
    return report


def inspect_smoke(jar: Path, work_root: Path) -> dict:
    started = time.monotonic()
    report = {"schema_version": 1, "status": "blocked", "synthetic_fixture_only": True,
              "real_project_datasets_read": 0, "melbourne_journeys_computed": 0,
              "temporary_workspace_removed": False, "problems": [],
              "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    inventory = runtime.inspect_runtime()
    report["runtime_inventory"] = inventory
    if inventory["blockers"]:
        report["problems"] = inventory["blockers"]
        return report
    try:
        jar = jar.resolve()
        check_engine(jar)
        work_root = check_work_root(work_root)
        if sha256(STREET_FIXTURE) != STREET_SHA256:
            raise ValueError("Synthetic street PBF fingerprint differs from the reviewed fixture.")
    except (OSError, ValueError) as error:
        report["problems"] = [str(error)]
        return report
    try:
        with tempfile.TemporaryDirectory(prefix="homereach-smoke-", dir=work_root) as directory:
            work = Path(directory).resolve()
            for name in ("config", "cache", "tmp"):
                (work / name).mkdir()
            shutil.copyfile(jar, work / ENGINE_NAME)
            check_engine(work / ENGINE_NAME)
            shutil.copyfile(STREET_FIXTURE, work / "streets.osm.pbf")
            if sha256(work / "streets.osm.pbf") != STREET_SHA256:
                raise ValueError("Copied street fixture fingerprint changed.")
            fixture.write_gtfs(work / "synthetic.gtfs.zip")
            report["fixture_sha256"] = {
                "streets.osm.pbf": sha256(work / "streets.osm.pbf"),
                "synthetic.gtfs.zip": sha256(work / "synthetic.gtfs.zip"),
            }
            report.update(run_worker(work))
        report["temporary_workspace_removed"] = True
    except (OSError, ValueError) as error:
        report.update(status="failed", problems=[str(error)])
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", required=True, type=Path, help="Existing reviewed local R5 JAR; never downloaded here.")
    parser.add_argument("--work-root", required=True, type=Path, help="Existing temporary parent directory outside checkout.")
    parser.add_argument("--json", action="store_true", help="Print the complete machine-readable result.")
    args = parser.parse_args(argv)
    report = inspect_smoke(args.jar, args.work_root)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
    else:
        print("SYNTHETIC ROUTING ENGINE SMOKE TEST:", report["status"].upper())
        print("Fictional street grid and timetable | No Melbourne travel-time claim")
        if isinstance(report.get("engine"), dict):
            print("Embedded JVM started:", report["engine"].get("jvm_started", False))
            print("Synthetic queries attempted:", report.get("queries_attempted", 0))
        if "timeline_diagnostics" in report:
            print("Timeline diagnostic:", json.dumps(report["timeline_diagnostics"]))
        for problem in report["problems"]:
            print("Detail:", problem)
        if report["status"] == "passed":
            print("Engine: r5py", report["engine"]["r5py"], "| R5 v7.5.1-r5py | SHA-256 verified")
            print("Java heap limit:", report["engine"]["max_heap_bytes"], "bytes | Python routing jobs: 1")
            print("Walking: positive itinerary verified")
            print("Active service: synthetic BUS route, stops, departure and five-minute ride verified")
            print("Inactive service: bus-only query returned no itinerary")
            print("Synthetic queries completed: 3")
        if report.get("worker_log_tail"):
            print(report["worker_log_tail"])
        print("Temporary workspace removed:", report["temporary_workspace_removed"])
        print("Real project datasets read: 0 | Melbourne journeys computed: 0")
        print("Not tested: Melbourne input compatibility, station access, transfers, accessibility, real journey timing")
    return {"passed": 0, "blocked": 2, "failed": 1}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
