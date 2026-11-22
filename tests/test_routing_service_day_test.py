"""Service-day orchestration fails closed without loading a routing engine."""
from __future__ import annotations

import builtins
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from types import SimpleNamespace
from zipfile import ZipFile

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_script(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    previous_path = sys.path.copy()
    previous_bytecode = sys.dont_write_bytecode
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = previous_path
        sys.dont_write_bytecode = previous_bytecode
    return module


m = load_script("routing_service_day_parent_under_test", "run_routing_service_day_test.py")
worker = load_script("routing_service_day_worker_under_test", "_routing_service_day_worker.py")


@pytest.fixture(autouse=True)
def prohibit_engine_and_network(monkeypatch):
    original_import = builtins.__import__

    def checked_import(name, *args, **kwargs):
        if name.split(".")[0] in {"r5py", "jpype", "java", "geopandas", "rasterio"}:
            raise AssertionError("A unit test attempted to import a routing runtime: " + name)
        return original_import(name, *args, **kwargs)

    def no_network(*args, **kwargs):
        raise AssertionError("A unit test attempted a network connection")

    monkeypatch.setattr(builtins, "__import__", checked_import)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)


def case_rows(case):
    if case["expected_route_id"] is None:
        return []
    query = datetime.fromisoformat(case["departure"])
    bus_departure = datetime.fromisoformat(case["expected_bus_departure"])
    bus_arrival = datetime.fromisoformat(case["expected_bus_arrival"])
    base = {"from_id": "synthetic_origin", "to_id": "synthetic_destination",
            "option": 0, "geometry_nonempty": True, "agency_id": None, "route_id": None,
            "start_stop_id": None, "end_stop_id": None}
    return [
        {**base, "mode": "WALK", "segment": 0, "departure_time": query.isoformat(),
         "travel_time_seconds": 12.0, "wait_time_seconds": 0.0, "distance_m": 11.1,
         "geometry": {"type": "LineString", "coordinates": [[0.0061, 0.018], [0.006, 0.018]]}},
        {**base, "mode": "BUS", "segment": 1, "departure_time": bus_departure.isoformat(),
         "travel_time_seconds": 300.0, "wait_time_seconds": (bus_departure - query).total_seconds() - 12,
         "distance_m": 2668.678, "agency_id": "SMOKE", "route_id": case["expected_route_id"],
         "start_stop_id": "SMOKE_WEST", "end_stop_id": "SMOKE_EAST",
         "geometry": {"type": "LineString", "coordinates": [[0.006, 0.018], [0.030, 0.018]]}},
        {**base, "mode": "WALK", "segment": 2,
         "departure_time": (bus_arrival + timedelta(seconds=60)).isoformat(),
         "travel_time_seconds": 12.0, "wait_time_seconds": 0.0, "distance_m": 11.254,
         "geometry": {"type": "LineString", "coordinates": [[0.030, 0.018], [0.0299, 0.018]]}},
    ]


@pytest.fixture
def complete_report():
    # Reuse reviewed adapter audit metadata only; the date-specific itinerary
    # rows below are made independently and are never claimed as engine output.
    evidence = json.loads((ROOT / "docs/evidence/routing_walk_correction_linux_2026-11-18.json").read_text())
    report = {key: deepcopy(evidence[key]) for key in
              ("engine", "itinerary_mode", "itinerary_adapter", "walking_correction", "walking")}
    report["engine"]["network_timezone"] = "Australia/Melbourne"
    report.update(status="completed", queries_attempted=len(m.fixture.CASES), walking_queries_attempted=1,
                  walking_crs="EPSG:4326", queries=[])
    for case in m.fixture.CASES:
        report["queries"].append({"id": case["id"], "departure": case["departure"],
                                  "departure_time_window_seconds": m.fixture.QUERY_WINDOW_SECONDS,
                                  "max_time_seconds": 1200, "transport_modes": ["BUS"],
                                  "geometry_crs": "EPSG:4326", "rows": case_rows(case)})
    return report


@pytest.fixture
def fake_inputs(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    for relative in m.SOURCE_PATHS:
        destination = checkout / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    street = checkout / "tests/fixtures/routing_smoke/streets.osm.pbf"
    street.parent.mkdir(parents=True)
    street.write_bytes(b"fake street input; never loaded")
    jar = tmp_path / "reviewed.jar"
    jar.write_bytes(b"fake engine; never executed")
    work_root = tmp_path / "external-work"
    work_root.mkdir()
    (work_root / "caller-owned.txt").write_text("preserve me", encoding="utf-8")
    monkeypatch.setattr(m, "ROOT", checkout)
    monkeypatch.setattr(m.smoke, "ROOT", checkout)
    monkeypatch.setattr(m.smoke, "STREET_FIXTURE", street)
    monkeypatch.setattr(m.smoke, "STREET_SHA256", hashlib.sha256(street.read_bytes()).hexdigest())
    monkeypatch.setattr(m.smoke, "ENGINE_BYTES", jar.stat().st_size)
    monkeypatch.setattr(m.smoke, "ENGINE_SHA256", hashlib.sha256(jar.read_bytes()).hexdigest())
    monkeypatch.setattr(m.runtime, "inspect_runtime", lambda: {"status": "prerequisites_passed", "blockers": []})
    return SimpleNamespace(checkout=checkout, street=street, jar=jar, work_root=work_root)


def assert_clean(inputs):
    assert sorted(path.name for path in inputs.work_root.iterdir()) == ["caller-owned.txt"]
    assert (inputs.work_root / "caller-owned.txt").read_text() == "preserve me"


def successful_worker(work):
    return {"status": "passed", "problems": []}


def test_complete_case_accounting_invokes_all_independent_validators(monkeypatch, complete_report):
    calls = {"integration": 0, "correction": 0, "geometry": 0, "duration": 0}
    for label, owner, name in (("integration", m.smoke, "validate_integration"),
                               ("correction", m.smoke, "validate_walking_correction"),
                               ("geometry", m.geometry, "audit_walk_geometry"),
                               ("duration", m.smoke, "walking_duration_diagnostics")):
        original = getattr(owner, name)

        def wrapped(*args, _label=label, _original=original, **kwargs):
            calls[_label] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(owner, name, wrapped)
    before = deepcopy(complete_report["queries"])
    assert m.validate_result(complete_report) == []
    assert calls == {"integration": 1, "correction": 1, "geometry": 8, "duration": 8}
    assert complete_report["positive_cases_passed"] == 8
    assert complete_report["negative_cases_passed"] == 4
    assert [item["id"] for item in complete_report["case_diagnostics"]] == [case["id"] for case in m.fixture.CASES]
    assert complete_report["queries"] == before


@pytest.mark.parametrize("key,value", [
    ("r5py", "0.0"), ("sha256", "0" * 64), ("jvm_started", False), ("jvm_started", 1),
    ("classpath_verified", False), ("temporary_directory_verified", False),
    ("python_routing_jobs", 2), ("python_routing_jobs", True), ("network_timezone", "UTC"),
    ("default_configuration_files", ["unreviewed.conf"]), ("java_version", "17.0.9"),
    ("java_version", 21.1), ("max_heap_bytes", 0), ("max_heap_bytes", True),
    ("max_heap_bytes", 1_073_741_825), ("max_heap_bytes", float("nan")),
])
def test_wrong_or_coerced_engine_identity_cannot_pass(complete_report, key, value):
    complete_report["engine"][key] = value
    if key == "java_version":
        complete_report["walking_correction"]["origin"]["helper"]["compiler_java_version"] = value
    assert m.validate_result(complete_report)


@pytest.mark.parametrize("key,value", [("queries_attempted", 11), ("queries_attempted", 12.0),
                                       ("walking_queries_attempted", 0), ("walking_queries_attempted", True)])
def test_query_attempt_counts_are_required(complete_report, key, value):
    complete_report[key] = value
    assert m.validate_result(complete_report)


@pytest.mark.parametrize("change", ["missing", "extra", "duplicate", "reordered", "not_list"])
def test_query_inventory_requires_every_fixed_case_once(complete_report, change):
    observations = complete_report["queries"]
    if change == "missing":
        observations.pop()
    elif change == "extra":
        observations.append(deepcopy(observations[-1]))
    elif change == "duplicate":
        observations[1] = deepcopy(observations[0])
    elif change == "reordered":
        observations.reverse()
    else:
        complete_report["queries"] = {}
    assert m.validate_result(complete_report)
    assert len(complete_report["case_diagnostics"]) == len(m.fixture.CASES)


@pytest.mark.parametrize("key,value", [("id", "wrong_case"), ("departure", "2026-10-14T08:00:00"),
                                       ("departure_time_window_seconds", 60), ("max_time_seconds", 1201),
                                       ("transport_modes", ["WALK", "BUS"]), ("error", "query failed")])
def test_query_settings_or_errors_fail_the_individual_case(complete_report, key, value):
    complete_report["queries"][0][key] = value
    assert m.validate_result(complete_report)
    assert complete_report["case_diagnostics"][0]["status"] == "failed"
    assert complete_report["case_diagnostics"][0]["problems"]
    assert complete_report["positive_cases_passed"] == 7


def test_empty_negative_query_with_error_is_not_a_success(complete_report):
    complete_report["queries"][-1]["error"] = "native query failed before returning rows"
    assert m.validate_result(complete_report)
    assert complete_report["negative_cases_passed"] == 3
    assert complete_report["case_diagnostics"][-1]["status"] == "failed"


@pytest.mark.parametrize("value", [None, [], "broken"])
def test_malformed_observations_remain_visible_in_case_diagnostics(complete_report, value):
    complete_report["queries"][0] = value
    assert m.validate_result(complete_report)
    assert complete_report["positive_cases_passed"] == 7
    diagnostic = complete_report["case_diagnostics"][0]
    assert diagnostic["id"] == m.fixture.CASES[0]["id"]
    assert diagnostic["status"] == "failed"
    assert len(complete_report["case_diagnostics"]) == 12


@pytest.mark.parametrize("scope", ["adapter", "index", "origin", "geometry"])
def test_each_adapter_scope_must_be_restored(complete_report, scope):
    audit = complete_report["itinerary_adapter"] if scope == "adapter" else complete_report["walking_correction"][scope]
    audit["restored"] = False
    assert m.validate_result(complete_report)


@pytest.mark.parametrize("change", ["source", "loader", "native_costs", "coverage"])
def test_correction_verification_must_remain_complete(complete_report, change):
    correction = complete_report["walking_correction"]
    if change == "source":
        complete_report["itinerary_adapter"]["source_sha256"] = {}
    elif change == "loader":
        correction["origin"]["helper_loader_closed"] = False
    elif change == "native_costs":
        correction["geometry"]["native_costs_preserved"] = False
    else:
        correction["index"]["coverage_after"]["missing_edge_candidates"] = 1
    assert m.validate_result(complete_report)


@pytest.mark.parametrize("kind", ["geometry", "duration"])
def test_walking_failures_are_part_of_case_status(monkeypatch, complete_report, kind):
    owner, name = ((m.geometry, "audit_walk_geometry") if kind == "geometry"
                   else (m.smoke, "walking_duration_diagnostics"))
    monkeypatch.setattr(owner, name, lambda report: {"problems": ["independent walking failure"]})
    assert m.validate_result(complete_report)
    assert complete_report["positive_cases_passed"] == 0
    assert all(check["status"] == "failed" for case, check in
               zip(m.fixture.CASES, complete_report["case_diagnostics"])
               if case["expected_route_id"] is not None)


def test_missing_previous_day_service_stays_failed_even_with_passing_calendar_controls(complete_report):
    missing_service = {"previous_service_24h", "previous_service_25h", "previous_service_32h", "calendar_addition"}
    for observed in complete_report["queries"]:
        if observed["id"] in missing_service:
            observed["rows"] = []
    assert m.validate_result(complete_report)
    statuses = {check["id"]: check["status"] for check in complete_report["case_diagnostics"]}
    assert {identifier for identifier, status in statuses.items() if status == "failed"} == missing_service
    assert statuses["daytime_calendar_addition"] == "passed"
    assert statuses["daytime_calendar_removal"] == "passed"
    assert complete_report["positive_cases_passed"] == 4
    assert complete_report["negative_cases_passed"] == 4


def test_worker_launch_uses_isolated_python_and_bounded_subprocess(monkeypatch, tmp_path, complete_report):
    def run(command, **kwargs):
        assert command == [sys.executable, "-I", "-B", str(m.WORKER)]
        assert kwargs["cwd"] == tmp_path
        assert kwargs["shell"] is False and kwargs["check"] is False
        assert kwargs["stdin"] == subprocess.DEVNULL and kwargs["stderr"] == subprocess.STDOUT
        assert kwargs["timeout"] == m.TIMEOUT_SECONDS
        assert kwargs["env"]["TEMP"] == str(tmp_path / "tmp")
        (tmp_path / "worker-result.json").write_text(json.dumps(complete_report), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(m.subprocess, "run", run)
    report = m.run_worker(tmp_path)
    assert report["status"] == "passed", report["problems"]
    assert report["positive_cases_passed"] == 8


@pytest.mark.parametrize("payload", [None, "{", "[]", "null", '{"value": NaN}', '{"value": Infinity}', '{"value": 1e999}'])
def test_malformed_or_nonfinite_worker_json_is_rejected(monkeypatch, tmp_path, payload):
    def run(command, **kwargs):
        if payload is not None:
            (tmp_path / "worker-result.json").write_text(payload, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(m.subprocess, "run", run)
    result = m.run_worker(tmp_path)
    assert result["status"] == "failed"
    assert any("Cannot validate worker report" in problem for problem in result["problems"])


def test_oversized_worker_report_is_rejected_before_decoding(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "REPORT_LIMIT_BYTES", 32)
    def run(command, **kwargs):
        (tmp_path / "worker-result.json").write_bytes(b" " * 33)
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(m.subprocess, "run", run)
    result = m.run_worker(tmp_path)
    assert result["status"] == "failed"
    assert "exceeds" in " ".join(result["problems"])


def test_nonzero_worker_exit_cannot_be_hidden_by_valid_results(monkeypatch, tmp_path, complete_report):
    def run(command, **kwargs):
        (tmp_path / "worker-result.json").write_text(json.dumps(complete_report), encoding="utf-8")
        return subprocess.CompletedProcess(command, 7)
    monkeypatch.setattr(m.subprocess, "run", run)
    result = m.run_worker(tmp_path)
    assert result["status"] == "failed"
    assert any("code 7" in problem for problem in result["problems"])


def test_timeout_keeps_failure_and_log_evidence(monkeypatch, tmp_path):
    def run(command, **kwargs):
        kwargs["stdout"].write(b"native search did not finish\n")
        kwargs["stdout"].flush()
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])
    monkeypatch.setattr(m.subprocess, "run", run)
    result = m.run_worker(tmp_path)
    assert result["status"] == "failed"
    assert "native search did not finish" in result["worker_log_tail"]
    assert any("exceeded" in problem for problem in result["problems"])


def test_success_stages_inputs_externally_and_cleans_owned_workspace(monkeypatch, fake_inputs):
    inputs = fake_inputs
    originals = {path: path.read_bytes() for path in (inputs.jar, inputs.street)}
    source_hashes = m._source_hashes()
    def run(work):
        assert work.parent == inputs.work_root
        assert work.name.startswith("homereach-service-day-")
        assert not work.is_relative_to(inputs.checkout)
        assert (work / m.smoke.ENGINE_NAME).read_bytes() == originals[inputs.jar]
        assert (work / "streets.osm.pbf").read_bytes() == originals[inputs.street]
        worker.verify_inputs(work)
        return successful_worker(work)
    monkeypatch.setattr(m, "run_worker", run)
    result = m.inspect_service_days(inputs.jar, inputs.work_root)
    assert result["status"] == "passed", result["problems"]
    assert result["protected_inputs_unchanged"] is True
    assert result["temporary_workspace_created"] is result["temporary_workspace_removed"] is True
    assert result["execution_source_sha256"] == source_hashes
    assert all(path.read_bytes() == value for path, value in originals.items())
    assert_clean(inputs)


def test_worker_cannot_replace_parent_scope_or_provenance(monkeypatch, fake_inputs):
    monkeypatch.setattr(m, "run_worker", lambda work: {
        "status": "passed", "problems": [], "routing_ready": True,
        "real_project_datasets_read": 9, "synthetic_fixture_only": False,
        "stage": "production", "execution_source_sha256": {"forged": "hash"}})
    result = m.inspect_service_days(fake_inputs.jar, fake_inputs.work_root)
    assert result["status"] == "failed"
    assert result["routing_ready"] is False
    assert result["real_project_datasets_read"] == 0
    assert result["synthetic_fixture_only"] is True
    assert result["stage"] == "synthetic_service_day_compatibility"
    assert result["execution_source_sha256"] == m._source_hashes()
    assert any("parent metadata" in problem for problem in result["problems"])
    assert_clean(fake_inputs)


@pytest.mark.parametrize("name", ["jar", "streets.osm.pbf", "service-day.gtfs.zip"])
def test_changed_staged_input_fails_and_is_cleaned(monkeypatch, fake_inputs, name):
    def run(work):
        (work / (m.smoke.ENGINE_NAME if name == "jar" else name)).write_bytes(b"changed staged input")
        return successful_worker(work)
    monkeypatch.setattr(m, "run_worker", run)
    result = m.inspect_service_days(fake_inputs.jar, fake_inputs.work_root)
    assert result["status"] == "failed"
    assert result["protected_inputs_unchanged"] is True
    assert any("staged input changed" in problem for problem in result["problems"])
    assert_clean(fake_inputs)


@pytest.mark.parametrize("target", ["jar", "street", "source"])
def test_changed_original_or_execution_source_cannot_pass(monkeypatch, fake_inputs, target):
    path = (fake_inputs.checkout / m.SOURCE_PATHS[0] if target == "source" else getattr(fake_inputs, target))
    def run(work):
        path.write_bytes(path.read_bytes() + b"\nmutation")
        return successful_worker(work)
    monkeypatch.setattr(m, "run_worker", run)
    result = m.inspect_service_days(fake_inputs.jar, fake_inputs.work_root)
    assert result["status"] == "failed"
    assert result["protected_inputs_unchanged"] is False
    assert any("original input or execution source changed" in problem for problem in result["problems"])
    assert_clean(fake_inputs)


def test_original_recheck_read_error_is_not_reported_as_unchanged(monkeypatch, fake_inputs):
    def run(work):
        fake_inputs.jar.unlink()
        return successful_worker(work)
    monkeypatch.setattr(m, "run_worker", run)
    result = m.inspect_service_days(fake_inputs.jar, fake_inputs.work_root)
    assert result["status"] == "failed"
    assert result["protected_inputs_unchanged"] is None
    assert any("Cannot recheck" in problem for problem in result["problems"])
    assert_clean(fake_inputs)


@pytest.mark.parametrize("failure_point", ["copy", "worker"])
def test_io_error_after_workspace_creation_is_failed_and_cleaned(monkeypatch, fake_inputs, failure_point):
    def fail(*args, **kwargs):
        raise OSError("controlled IO failure")
    monkeypatch.setattr(m.shutil if failure_point == "copy" else m,
                        "copyfile" if failure_point == "copy" else "run_worker", fail)
    result = m.inspect_service_days(fake_inputs.jar, fake_inputs.work_root)
    assert result["status"] == "failed"
    assert result["temporary_workspace_created"] is True
    assert result["temporary_workspace_removed"] is True
    assert_clean(fake_inputs)


def test_cleanup_failure_prevents_success(monkeypatch, fake_inputs):
    created = []
    class LeakyDirectory:
        def __init__(self, *, prefix, dir):
            self.path = Path(dir) / (prefix + "controlled-leak")
        def __enter__(self):
            self.path.mkdir()
            created.append(self.path)
            return str(self.path)
        def __exit__(self, *args):
            return False
    monkeypatch.setattr(m.tempfile, "TemporaryDirectory", LeakyDirectory)
    monkeypatch.setattr(m, "run_worker", successful_worker)
    try:
        result = m.inspect_service_days(fake_inputs.jar, fake_inputs.work_root)
        assert result["status"] == "failed"
        assert result["temporary_workspace_removed"] is False
        assert any("cleanup did not complete" in problem for problem in result["problems"])
    finally:
        for path in created:
            shutil.rmtree(path)
    assert_clean(fake_inputs)


@pytest.mark.parametrize("location", ["inside", "missing", "symlink_inside"])
def test_work_root_must_exist_outside_the_checkout(monkeypatch, tmp_path, fake_inputs, location):
    if location == "inside":
        path = fake_inputs.checkout
    elif location == "missing":
        path = tmp_path / "not-created"
    else:
        path = tmp_path / "link-to-checkout"
        try:
            path.symlink_to(fake_inputs.checkout, target_is_directory=True)
        except OSError:
            pytest.skip("Directory symlinks are unavailable on this platform")
    monkeypatch.setattr(m, "run_worker", lambda work: pytest.fail("worker must not run"))
    result = m.inspect_service_days(fake_inputs.jar, path)
    assert result["status"] == "blocked"
    assert result["temporary_workspace_created"] is False
    assert_clean(fake_inputs)


def test_missing_runtime_blocks_before_reading_engine_or_fixture(monkeypatch, tmp_path):
    monkeypatch.setattr(m.runtime, "inspect_runtime", lambda: {"status": "blocked", "blockers": ["r5py unavailable"]})
    monkeypatch.setattr(m.smoke, "check_engine", lambda path: pytest.fail("must not read engine"))
    monkeypatch.setattr(m, "run_worker", lambda work: pytest.fail("must not launch worker"))
    result = m.inspect_service_days(tmp_path / "missing.jar", tmp_path / "missing-work")
    assert result["status"] == "blocked"
    assert result["problems"] == ["r5py unavailable"]
    assert result["temporary_workspace_created"] is False
    assert result["real_project_datasets_read"] == 0


@pytest.mark.parametrize("mutation", ["jar", "street", "table", "missing", "duplicate", "extra"])
def test_worker_rejects_tampered_staged_inputs_before_runtime_import(tmp_path, fake_inputs, mutation):
    work = tmp_path / "worker-verification"
    work.mkdir()
    shutil.copyfile(fake_inputs.jar, work / m.smoke.ENGINE_NAME)
    shutil.copyfile(fake_inputs.street, work / "streets.osm.pbf")
    archive = work / "service-day.gtfs.zip"
    m.fixture.write_gtfs(archive)
    worker.verify_inputs(work)
    if mutation in {"jar", "street"}:
        path = work / (m.smoke.ENGINE_NAME if mutation == "jar" else "streets.osm.pbf")
        path.write_bytes(b"tampered")
    else:
        members = list(m.fixture.gtfs_tables().items())
        if mutation == "table":
            members[0] = (members[0][0], members[0][1] + b"tampered\n")
        elif mutation == "missing":
            members.pop()
        elif mutation == "duplicate":
            members.append(members[0])
        else:
            members.append(("../unexpected.txt", b"not extracted"))
        archive.unlink()
        with ZipFile(archive, "w") as handle:
            for name, value in members:
                if mutation == "duplicate" and name in handle.namelist():
                    with pytest.warns(UserWarning, match="Duplicate name"):
                        handle.writestr(name, value)
                else:
                    handle.writestr(name, value)
    with pytest.raises(ValueError):
        worker.verify_inputs(work)
    assert not (tmp_path / "unexpected.txt").exists()


@pytest.mark.parametrize("status,code", [("passed", 0), ("blocked", 2), ("failed", 1)])
def test_cli_json_preserves_outcome_and_exit_code(monkeypatch, capsys, status, code):
    report = {"status": status, "problems": []}
    monkeypatch.setattr(m, "inspect_service_days", lambda jar, work: report)
    assert m.main(["--jar", "engine.jar", "--work-root", "external-work", "--json"]) == code
    assert json.loads(capsys.readouterr().out) == report
