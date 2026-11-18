"""The synthetic engine command has bounded, independently checked outcomes.

These tests exercise orchestration and report validation without installing or
importing R5, JPype, GeoPandas or an embedded JVM.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_routing_smoke_test.py"
spec = importlib.util.spec_from_file_location("routing_smoke_parent", SCRIPT)
m = importlib.util.module_from_spec(spec)
previous_path = sys.path.copy()
try:
    sys.path.insert(0, str(SCRIPT.parent))
    spec.loader.exec_module(m)
finally:
    sys.path[:] = previous_path


def leg(mode, departure, duration, distance, *, segment=0):
    return {
        "from_id": "synthetic_origin", "to_id": "synthetic_destination",
        "option": 0, "segment": segment, "mode": mode,
        "departure_time": departure, "travel_time_seconds": duration,
        "wait_time_seconds": 0, "distance_m": distance, "geometry_nonempty": True,
        "agency_id": None, "route_id": None, "start_stop_id": None, "end_stop_id": None,
    }


@pytest.fixture
def completed_report():
    bus = leg("BUS", "2026-10-13T08:05:00", 300, 2668, segment=1)
    bus.update(agency_id="SMOKE", route_id="SMOKE_BUS", start_stop_id="SMOKE_WEST",
               end_stop_id="SMOKE_EAST", wait_time_seconds=289)
    return {
        "status": "completed", "queries_attempted": 3,
        "engine": {
            "sha256": m.ENGINE_SHA256, "r5py": "1.1.7", "java_version": "21.0.10",
            "jvm_started": True, "max_heap_bytes": 1_073_741_824,
            "classpath_verified": True, "temporary_directory_verified": True,
            "python_routing_jobs": 1,
        },
        "walking": [leg("WALK", "2026-10-13T08:00:00", 2646, 2646)],
        "transit": [leg("WALK", "2026-10-13T08:00:00", 11, 11), bus,
                    leg("WALK", "2026-10-13T08:10:00", 11, 11, segment=2)],
        "no_service": [],
    }


@pytest.fixture
def passed_inventory(monkeypatch):
    inventory = {"status": "prerequisites_passed", "blockers": []}
    monkeypatch.setattr(m.runtime, "inspect_runtime", lambda: deepcopy(inventory))
    return inventory


@pytest.fixture
def fake_inputs(tmp_path, monkeypatch, passed_inventory):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    jar = inputs / "reviewed.jar"
    jar.write_bytes(b"fake engine bytes; not executable")
    street = inputs / "streets.osm.pbf"
    street.write_bytes(b"fake street bytes; not loaded")
    work_root = tmp_path / "work"
    work_root.mkdir()
    monkeypatch.setattr(m, "ENGINE_BYTES", jar.stat().st_size)
    monkeypatch.setattr(m, "ENGINE_SHA256", hashlib.sha256(jar.read_bytes()).hexdigest())
    monkeypatch.setattr(m, "STREET_FIXTURE", street)
    monkeypatch.setattr(m, "STREET_SHA256", hashlib.sha256(street.read_bytes()).hexdigest())
    return jar, street, work_root


def test_success_requires_actual_walking_bus_and_inactive_service_observations(completed_report):
    assert m.validate_outcomes(completed_report) == []


def test_missing_inactive_query_output_is_not_evidence_of_no_service(completed_report):
    del completed_report["no_service"]
    assert any("inactive-date" in problem for problem in m.validate_outcomes(completed_report))


def test_committed_streets_match_reviewed_generator_and_fingerprint():
    xml = m.STREET_FIXTURE.with_suffix("")
    assert xml.read_text(encoding="utf-8") == m.fixture.street_xml().decode("utf-8")
    assert m.sha256(m.STREET_FIXTURE) == m.STREET_SHA256


def test_captured_native_engine_failure_cannot_be_relabelled_as_a_pass():
    evidence = m.ROOT / "docs/evidence/routing_smoke_linux_2026-11-18.json"
    report = json.loads(evidence.read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    # A completed engine process is necessary but insufficient for validity.
    report["status"] = "completed"
    assert any("chronology failed" in problem for problem in m.validate_outcomes(report))
    assert any("waits failed" in problem for problem in m.validate_outcomes(report))


@pytest.mark.parametrize("change,expected", [
    ("query_count", "all three"),
    ("engine_hash", "engine identity"),
    ("r5py_version", "engine identity"),
    ("heap_over_limit", "heap"),
    ("heap_nan", "heap"),
    ("classpath", "paths"),
    ("temporary_directory", "paths"),
    ("missing_walking", "Walking did not return"),
    ("nonfinite_walking", "Nonpositive/nonfinite"),
    ("no_actual_bus", "No actual BUS"),
    ("inactive_transit", "inactive-date"),
    ("wrong_route", "synthetic route"),
    ("wrong_destination", "Wrong origin/destination"),
    ("wrong_departure", "synthetic timetable"),
    ("wrong_bus_duration", "five-minute"),
    ("missing_geometry", "geometry"),
    ("wrong_mode", "mode"),
])
def test_incomplete_or_inconsistent_engine_results_never_pass(completed_report, change, expected):
    report = completed_report
    if change == "query_count":
        report["queries_attempted"] = 2
    elif change == "engine_hash":
        report["engine"]["sha256"] = "0" * 64
    elif change == "r5py_version":
        report["engine"]["r5py"] = "0.0"
    elif change == "heap_over_limit":
        report["engine"]["max_heap_bytes"] = 1_073_741_825
    elif change == "heap_nan":
        report["engine"]["max_heap_bytes"] = float("nan")
    elif change == "classpath":
        report["engine"]["classpath_verified"] = False
    elif change == "temporary_directory":
        report["engine"]["temporary_directory_verified"] = False
    elif change == "missing_walking":
        report["walking"] = []
    elif change == "nonfinite_walking":
        report["walking"][0]["travel_time_seconds"] = float("inf")
    elif change == "no_actual_bus":
        report["transit"] = deepcopy(report["walking"])
    elif change == "inactive_transit":
        report["no_service"] = deepcopy(report["transit"])
    elif change == "wrong_route":
        report["transit"][1]["route_id"] = "UNEXPECTED_ROUTE"
    elif change == "wrong_destination":
        report["walking"][0]["to_id"] = "different_destination"
    elif change == "wrong_departure":
        report["transit"][1]["departure_time"] = "2026-10-13T09:05:00"
    elif change == "wrong_bus_duration":
        report["transit"][1]["travel_time_seconds"] = 301
    elif change == "missing_geometry":
        report["transit"][1]["geometry_nonempty"] = False
    else:
        report["walking"][0]["mode"] = "CAR"
    problems = m.validate_outcomes(report)
    assert problems
    assert any(expected in problem for problem in problems)


@pytest.mark.parametrize("field,value", [("jvm_started", False), ("python_routing_jobs", 2),
                                        ("java_version", "17.0.9")])
def test_observed_jvm_and_thread_baseline_is_checked(completed_report, field, value):
    completed_report["engine"][field] = value
    assert m.validate_outcomes(completed_report)


def test_timeline_groups_options_independently_without_mutating_or_reordering_input(completed_report):
    first = deepcopy(completed_report["transit"])
    second = deepcopy(first)
    for row in second:
        row["option"] = 1
    second[1]["departure_time"] = "2026-10-13T08:10:00"
    second[1]["wait_time_seconds"] = 589
    second[2]["departure_time"] = "2026-10-13T08:15:00"
    rows = [second[2], first[1], second[0], first[2], second[1], first[0]]
    original = deepcopy(rows)
    diagnostic = m.timeline_diagnostics(rows)
    assert diagnostic == {"options_checked": 2, "overlaps": 0, "wait_mismatches": 0,
                          "malformed_options": 0, "examples": []}
    assert rows == original


def test_bus_cannot_depart_before_the_access_walk_arrives(completed_report):
    # This reproduces the observed shared-access-leg symptom: a later walk's
    # timestamp has appeared on an option using the 08:05 departure.
    completed_report["transit"][0]["departure_time"] = "2026-10-13T08:09:13"
    diagnostic = m.timeline_diagnostics(completed_report["transit"])
    assert diagnostic["overlaps"] == 1
    assert diagnostic["wait_mismatches"] == 1
    assert diagnostic["examples"] == [{
        "option": 0, "segment": 1, "previous_arrival": "2026-10-13T08:09:24",
        "departure": "2026-10-13T08:05:00", "overlap_seconds": 264.0,
    }]
    problems = m.validate_outcomes(completed_report)
    assert any("chronology failed" in problem for problem in problems)


def test_bus_wait_must_match_gap_even_when_leg_times_are_ordered(completed_report):
    completed_report["transit"][1]["wait_time_seconds"] = 0
    diagnostic = m.timeline_diagnostics(completed_report["transit"])
    assert diagnostic["overlaps"] == 0
    assert diagnostic["wait_mismatches"] == 1
    assert any("waits failed" in problem for problem in m.validate_outcomes(completed_report))


@pytest.mark.parametrize("offset,expected_mismatches", [(1.0, 0), (1.01, 1)])
def test_wait_comparison_permits_at_most_one_second_of_absolute_rounding(completed_report, offset, expected_mismatches):
    completed_report["transit"][1]["wait_time_seconds"] += offset
    diagnostic = m.timeline_diagnostics(completed_report["transit"])
    assert diagnostic["wait_mismatches"] == expected_mismatches


@pytest.mark.parametrize("field,value", [
    ("departure_time", "NaT"), ("departure_time", None),
    ("segment", 0), ("segment", 5),
    ("wait_time_seconds", -1), ("wait_time_seconds", float("nan")),
])
def test_malformed_timeline_is_reported_instead_of_silently_skipped(completed_report, field, value):
    completed_report["transit"][1][field] = value
    diagnostic = m.timeline_diagnostics(completed_report["transit"])
    assert diagnostic["malformed_options"] == 1
    assert any("malformed timestamps" in problem for problem in m.validate_outcomes(completed_report))


def test_blocked_prerequisites_prevent_file_checks_and_worker_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(m.runtime, "inspect_runtime", lambda: {"blockers": ["Missing r5py."]})
    monkeypatch.setattr(m, "check_engine", lambda _: pytest.fail("Engine file inspected before prerequisites."))
    monkeypatch.setattr(m, "run_worker", lambda _: pytest.fail("Worker started before prerequisites."))
    report = m.inspect_smoke(tmp_path / "absent.jar", tmp_path)
    assert report["status"] == "blocked"
    assert report["problems"] == ["Missing r5py."]
    assert list(tmp_path.iterdir()) == []


def test_missing_local_jar_does_not_launch_worker_or_create_workspace(tmp_path, monkeypatch, passed_inventory):
    monkeypatch.setattr(m, "run_worker", lambda _: pytest.fail("Missing JAR was executed."))
    report = m.inspect_smoke(tmp_path / "missing.jar", tmp_path)
    assert report["status"] == "blocked"
    assert "missing" in report["problems"][0]
    assert list(tmp_path.iterdir()) == []


def test_changed_jar_content_is_rejected_even_at_the_expected_size(fake_inputs, monkeypatch):
    jar, _, work_root = fake_inputs
    jar.write_bytes(b"x" * jar.stat().st_size)
    monkeypatch.setattr(m, "run_worker", lambda _: pytest.fail("Modified JAR was executed."))
    report = m.inspect_smoke(jar, work_root)
    assert report["status"] == "blocked"
    assert "SHA-256" in report["problems"][0]
    assert list(work_root.iterdir()) == []


@pytest.mark.parametrize("choice", ["missing", "root", "descendant"])
def test_work_root_must_exist_outside_the_checkout(tmp_path, monkeypatch, choice):
    checkout = tmp_path / "checkout"
    child = checkout / "nested"
    child.mkdir(parents=True)
    monkeypatch.setattr(m, "ROOT", checkout)
    path = {"missing": tmp_path / "absent", "root": checkout, "descendant": child}[choice]
    with pytest.raises(ValueError):
        m.check_work_root(path)


def test_work_root_cannot_escape_containment_through_a_symlink(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    alias = tmp_path / "appears_external"
    try:
        alias.symlink_to(checkout, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Symlink creation unavailable: {error}")
    monkeypatch.setattr(m, "ROOT", checkout)
    with pytest.raises(ValueError, match="outside"):
        m.check_work_root(alias)


def test_staging_keeps_inputs_unchanged_and_removes_generated_workspace(fake_inputs, monkeypatch):
    jar, street, work_root = fake_inputs
    originals = {jar: jar.read_bytes(), street: street.read_bytes()}
    visited = []

    def worker(work):
        visited.append(work)
        assert work.parent == work_root
        assert work.name.startswith("homereach-smoke-")
        assert (work / m.ENGINE_NAME).read_bytes() == originals[jar]
        assert (work / "streets.osm.pbf").read_bytes() == originals[street]
        assert (work / "synthetic.gtfs.zip").is_file()
        assert all((work / folder).is_dir() for folder in ("tmp", "config", "cache"))
        return {"status": "passed", "problems": [], "queries_attempted": 3}

    monkeypatch.setattr(m, "run_worker", worker)
    report = m.inspect_smoke(jar, work_root)
    assert report["status"] == "passed"
    assert report["temporary_workspace_removed"] is True
    assert report["synthetic_fixture_only"] is True
    assert report["real_project_datasets_read"] == report["melbourne_journeys_computed"] == 0
    assert report["fixture_sha256"]["streets.osm.pbf"] == hashlib.sha256(originals[street]).hexdigest()
    assert len(visited) == 1
    assert not visited[0].exists()
    assert list(work_root.iterdir()) == []
    assert {path: path.read_bytes() for path in originals} == originals


def test_copy_is_verified_again_before_worker_launch(fake_inputs, monkeypatch):
    jar, _, work_root = fake_inputs
    original_copy = shutil.copyfile

    def changing_copy(source, destination):
        result = original_copy(source, destination)
        if Path(source) == jar:
            Path(destination).write_bytes(b"x" * jar.stat().st_size)
        return result

    monkeypatch.setattr(m.shutil, "copyfile", changing_copy)
    monkeypatch.setattr(m, "run_worker", lambda _: pytest.fail("Changed staged JAR was executed."))
    report = m.inspect_smoke(jar, work_root)
    assert report["status"] == "failed"
    assert "SHA-256" in report["problems"][0]
    assert list(work_root.iterdir()) == []


def test_child_environment_retains_jdk_and_redirects_only_run_specific_state(tmp_path, monkeypatch):
    jdk = str(tmp_path / "installed jdk")
    monkeypatch.setenv("JAVA_HOME", jdk)
    for name in ("JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS", "CLASSPATH",
                 "PYTHONPATH", "PYTHONSTARTUP"):
        monkeypatch.setenv(name, "unexpected injection")
    before = os.environ.copy()
    environment = m.child_environment(tmp_path / "run")
    assert environment["JAVA_HOME"] == jdk
    assert environment.get("HOME") == before.get("HOME")
    assert not ({key.upper() for key in environment} & {
        "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS", "CLASSPATH",
        "PYTHONPATH", "PYTHONSTARTUP",
    })
    for name in ("TMPDIR", "TEMP", "TMP"):
        assert environment[name] == str(tmp_path / "run" / "tmp")
    assert environment["XDG_CONFIG_HOME"] == str(tmp_path / "run" / "config")
    assert environment["XDG_CACHE_HOME"] == str(tmp_path / "run" / "cache")
    assert environment["PROJ_NETWORK"] == "OFF"
    assert environment["OMP_NUM_THREADS"] == "1"
    assert os.environ == before


def test_worker_uses_fixed_interpreter_script_and_bounded_subprocess(tmp_path, monkeypatch, completed_report):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        kwargs["stdout"].write(b"Native output is not the JSON result.\n")
        (tmp_path / "worker-result.json").write_text(json.dumps(completed_report), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(m.subprocess, "run", run)
    report = m.run_worker(tmp_path)
    assert report["status"] == "passed"
    assert report["problems"] == []
    command, options = calls[0]
    assert command == [sys.executable, "-I", "-B", str(m.WORKER)]
    assert options["cwd"] == tmp_path
    assert options["shell"] is False
    assert options["stdin"] == subprocess.DEVNULL
    assert options["stderr"] == subprocess.STDOUT
    assert options["timeout"] == 180
    assert options["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
    assert options["env"]["TMPDIR"] == str(tmp_path / "tmp")
    assert "worker_log_tail" not in report


def test_nonzero_worker_cannot_pass_with_an_otherwise_valid_report(tmp_path, monkeypatch, completed_report):
    def run(command, **kwargs):
        (tmp_path / "worker-result.json").write_text(json.dumps(completed_report), encoding="utf-8")
        kwargs["stdout"].write(b"worker failure details")
        return subprocess.CompletedProcess(command, 7)

    monkeypatch.setattr(m.subprocess, "run", run)
    report = m.run_worker(tmp_path)
    assert report["status"] == "failed"
    assert any("code 7" in problem for problem in report["problems"])
    assert "worker failure details" in report["worker_log_tail"]


def test_one_inconsistent_option_fails_the_run_and_raw_legs_remain_visible(tmp_path, monkeypatch, completed_report):
    bad_option = deepcopy(completed_report["transit"])
    for row in bad_option:
        row["option"] = 1
    bad_option[0]["departure_time"] = "2026-10-13T08:09:13"
    completed_report["transit"].extend(bad_option)
    original = deepcopy(completed_report["transit"])

    def run(command, **_):
        (tmp_path / "worker-result.json").write_text(json.dumps(completed_report), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(m.subprocess, "run", run)
    report = m.run_worker(tmp_path)
    assert report["status"] == "failed"
    assert report["timeline_diagnostics"]["options_checked"] == 2
    assert report["timeline_diagnostics"]["overlaps"] == 1
    assert report["transit"] == original


def test_worker_timeout_is_reported_with_bounded_diagnostics(tmp_path, monkeypatch):
    def timeout(command, **kwargs):
        kwargs["stdout"].write(b"x" * 20_000)
        kwargs["stdout"].flush()
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(m.subprocess, "run", timeout)
    report = m.run_worker(tmp_path)
    assert report["status"] == "failed"
    assert "180 seconds" in report["problems"][0]
    assert len(report["worker_log_tail"]) <= 12_000


@pytest.mark.parametrize("payload", [
    None, "not json", "[]", '{"status":"completed","engine":null}',
    '{"status":"completed","engine":{"max_heap_bytes":NaN}}',
    '{"status":"completed","engine":{"max_heap_bytes":Infinity}}',
    '{"status":"completed","engine":{"max_heap_bytes":1e999}}',
])
def test_missing_or_malformed_worker_report_is_a_serializable_failure(tmp_path, monkeypatch, payload):
    def run(command, **_):
        if payload is not None:
            (tmp_path / "worker-result.json").write_text(payload, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(m.subprocess, "run", run)
    report = m.run_worker(tmp_path)
    assert report["status"] == "failed"
    assert report["problems"]
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("event,args", [
    ("open", ("OUTSIDE", "w", os.O_WRONLY)),
    ("open", ("OUTSIDE", "r+", os.O_RDWR)),
    ("os.mkdir", ("OUTSIDE", 0o755, -1)),
    ("os.remove", ("OUTSIDE", -1)),
    ("os.rmdir", ("OUTSIDE", -1)),
    ("os.truncate", ("OUTSIDE", 0)),
    ("os.rename", ("INSIDE", "OUTSIDE", -1, -1)),
    ("os.link", ("OUTSIDE", "INSIDE", -1, -1)),
    ("os.symlink", ("INSIDE", "INSIDE", -1)),
    ("socket.getaddrinfo", ("example.invalid", 443, 0, 0, 0)),
    ("socket.connect", (object(), ("127.0.0.1", 443))),
])
def test_python_guard_denies_outside_mutations_and_network(tmp_path, event, args):
    work = tmp_path / "run"
    work.mkdir()
    mapping = {"INSIDE": str(work / "file"), "OUTSIDE": str(tmp_path / "outside")}
    rewritten = tuple(mapping.get(value, value) if isinstance(value, str) else value for value in args)
    with pytest.raises(PermissionError):
        m.python_write_guard(work)(event, rewritten)


def test_python_guard_permits_reads_and_temporary_writes_but_not_directory_fds(tmp_path):
    work = tmp_path / "run"
    work.mkdir()
    guard = m.python_write_guard(work)
    guard("open", (str(tmp_path / "outside-readable"), "r", os.O_RDONLY))
    guard("open", (str(work / "output"), "w", os.O_WRONLY | os.O_CREAT))
    guard("os.mkdir", (str(work / "new"), 0o755, -1))
    guard("os.rename", (str(work / "old"), str(work / "new"), -1, -1))
    guard("open", (1, "w", os.O_WRONLY))
    with pytest.raises(PermissionError, match="descriptor"):
        guard("open", (99, "w", os.O_WRONLY))
    with pytest.raises(PermissionError, match="descriptor"):
        guard("os.mkdir", ("relative-name", 0o755, 99))


def test_installed_python_guard_allows_temp_artifacts_and_preserves_outside_file(tmp_path):
    work = tmp_path / "run"
    work.mkdir()
    outside = tmp_path / "preserved.txt"
    outside.write_text("preserved input", encoding="utf-8")
    runner = """
import json, os, sys
from pathlib import Path
sys.dont_write_bytecode = True
scripts, work, outside = sys.argv[1:]
sys.path.insert(0, scripts)
import run_routing_smoke_test as smoke
work, outside = Path(work), Path(outside)
sys.addaudithook(smoke.python_write_guard(work))
assert outside.read_text(encoding='utf-8') == 'preserved input'
inside = work / 'artifact.txt'
inside.write_text('temporary output', encoding='utf-8')
inside.rename(work / 'renamed.txt')
denied = []
for label, operation in (
    ('write', lambda: outside.write_text('bad', encoding='utf-8')),
    ('unlink', outside.unlink),
    ('truncate', lambda: os.truncate(outside, 0)),
    ('rename', lambda: (work / 'renamed.txt').rename(outside)),
):
    try:
        operation()
    except PermissionError:
        denied.append(label)
print(json.dumps({'denied': denied}))
"""
    result = subprocess.run(
        [sys.executable, "-S", "-c", runner, str(SCRIPT.parent), str(work), str(outside)],
        cwd=tmp_path, stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["denied"] == ["write", "unlink", "truncate", "rename"]
    assert outside.read_text(encoding="utf-8") == "preserved input"
    assert (work / "renamed.txt").read_text(encoding="utf-8") == "temporary output"


@pytest.mark.parametrize("status,code", [("passed", 0), ("blocked", 2), ("failed", 1)])
def test_cli_json_has_distinct_status_codes_without_native_output(monkeypatch, capsys, status, code):
    report = {"status": status, "problems": [], "synthetic_fixture_only": True,
              "melbourne_journeys_computed": 0, "temporary_workspace_removed": status == "passed"}
    monkeypatch.setattr(m, "inspect_smoke", lambda *_: report)
    assert m.main(["--jar", "reviewed.jar", "--work-root", "temporary", "--json"]) == code
    captured = capsys.readouterr()
    assert json.loads(captured.out) == report
    assert captured.err == ""


def test_fresh_help_uses_only_stdlib_and_does_not_write_checkout(tmp_path):
    checkout = tmp_path / "checkout"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    for name in ("run_routing_smoke_test.py", "check_routing_runtime.py", "routing_smoke_fixture.py"):
        shutil.copyfile(SCRIPT.parent / name, scripts / name)
    before = {path.relative_to(checkout): path.read_bytes() for path in checkout.rglob("*") if path.is_file()}
    runner = """
import runpy, sys
script = sys.argv[1]
sys.path.insert(0, str(__import__('pathlib').Path(script).parent))
class DenyRuntimeImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'r5py', 'jpype', 'geopandas', 'pandas', 'numpy', 'shapely', 'pyproj', 'rasterio'}:
            raise AssertionError('Unexpected engine import: ' + fullname)
sys.meta_path.insert(0, DenyRuntimeImports())
sys.argv = [script, '--help']
runpy.run_path(script, run_name='__main__')
"""
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() not in {"PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX"}}
    result = subprocess.run([sys.executable, "-S", "-c", runner, str(scripts / SCRIPT.name)],
                            cwd=tmp_path, env=environment, capture_output=True, text=True,
                            stdin=subprocess.DEVNULL, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    assert "--jar" in result.stdout
    assert result.stderr == ""
    after = {path.relative_to(checkout): path.read_bytes() for path in checkout.rglob("*") if path.is_file()}
    assert after == before
