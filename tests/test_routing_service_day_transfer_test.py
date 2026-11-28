"""Protect the native transfer baseline's process boundary and explicit model."""
from __future__ import annotations

import builtins
from copy import deepcopy
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

from test_routing_service_day_transfer import valid_baseline_report


ROOT = Path(__file__).resolve().parents[1]


def load_script(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    old_path, old_bytecode = sys.path.copy(), sys.dont_write_bytecode
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = old_path
        sys.dont_write_bytecode = old_bytecode
    return module


m = load_script("routing_transfer_parent_under_test", "run_routing_service_day_transfer_test.py")
worker = load_script("routing_transfer_worker_under_test", "_routing_service_day_transfer_worker.py")


@pytest.fixture(autouse=True)
def prohibit_engine_and_network(monkeypatch):
    original_import = builtins.__import__

    def checked_import(name, *args, **kwargs):
        if name.split(".")[0] in {"r5py", "jpype", "java", "geopandas", "rasterio"}:
            raise AssertionError("Unit test attempted a native routing import: " + name)
        return original_import(name, *args, **kwargs)

    def no_network(*args, **kwargs):
        raise AssertionError("Unit test attempted a network connection")

    monkeypatch.setattr(builtins, "__import__", checked_import)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)


@pytest.fixture
def fake_inputs(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    for relative in m.SOURCE_PATHS:
        destination = checkout / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    street = checkout / "tests/fixtures/routing_smoke/streets.osm.pbf"
    street.parent.mkdir(parents=True, exist_ok=True)
    street.write_bytes(b"fake streets; no native code is executed")
    jar = tmp_path / "reviewed.jar"
    jar.write_bytes(b"fake reviewed engine; never loaded")
    external = tmp_path / "external-work"
    external.mkdir()
    (external / "caller-owned.txt").write_text("keep this", encoding="utf-8")
    monkeypatch.setattr(m, "ROOT", checkout)
    monkeypatch.setattr(m.smoke, "ROOT", checkout)
    monkeypatch.setattr(m.smoke, "STREET_FIXTURE", street)
    monkeypatch.setattr(m.smoke, "STREET_SHA256", hashlib.sha256(street.read_bytes()).hexdigest())
    monkeypatch.setattr(m.smoke, "ENGINE_BYTES", jar.stat().st_size)
    monkeypatch.setattr(m.smoke, "ENGINE_SHA256", hashlib.sha256(jar.read_bytes()).hexdigest())
    monkeypatch.setattr(m.runtime, "inspect_runtime", lambda: {"status": "prerequisites_passed", "blockers": []})
    return SimpleNamespace(checkout=checkout, street=street, jar=jar, work_root=external)


def assert_clean(inputs):
    assert sorted(p.name for p in inputs.work_root.iterdir()) == ["caller-owned.txt"]
    assert (inputs.work_root / "caller-owned.txt").read_text() == "keep this"


def accepted_process_stub(work):
    # Only for process-boundary tests; this is not a native-engine observation.
    return {"status": "passed", "problems": []}


@pytest.fixture
def complete_baseline_report():
    # All native case states are hand-declared, never produced by the worker or
    # expected fixture builder. This baseline must retain its missing mixed path.
    report = valid_baseline_report()
    report.update(
        status="completed", networks_attempted=8, queries_attempted=8,
        walking_queries_attempted=0, native_transit_router_modified=False,
        transit_itinerary_serialization_used=False,
        fixed_artificial_access_egress_costs=True,
        interstop_transfer_model="scoped_empty_street_transfers",
        physical_walking_validated=False,
        request_source_sha256={
            "r5/regional_task.py": "2cb5729eb461fc66d7e482f833373121e87e8b21cc68f81f46cc4d5ea8be6876",
            "r5/trip_planner.py": "541bcf3ec644bb717195518699ad540d1c448330539e26b1f36cd850ff7674a7",
        },
        engine={"r5py": "1.1.7",
                "sha256": "d50be106cadd7b636cfc0e209052767d7df570629f79fdf98ecd5cf5d2d89be7",
                "jvm_started": True, "classpath_verified": True,
                "temporary_directory_verified": True, "python_routing_jobs": 1,
                "default_configuration_files": [], "java_version": "21.0.10",
                "max_heap_bytes": 1073741824},
    )
    return report


def test_valid_native_baseline_retains_failure_and_preserves_raw_observations(complete_baseline_report):
    before = deepcopy(complete_baseline_report["cases"])
    problems = m.validate_result(complete_baseline_report)
    assert problems
    assert all("mixed_day_transfer" in problem for problem in problems)
    assert complete_baseline_report["cases_passed"] == 7
    assert complete_baseline_report["same_day_control_passed"] is True
    assert complete_baseline_report["cases"] == before


@pytest.mark.parametrize("field,value", [
    ("r5py", "1.1.8"), ("sha256", "0" * 64), ("jvm_started", False),
    ("classpath_verified", 1), ("temporary_directory_verified", False),
    ("python_routing_jobs", 2), ("default_configuration_files", ["unreviewed.yaml"]),
    ("max_heap_bytes", 1073741825), ("max_heap_bytes", True), ("java_version", "17.0.9"),
])
def test_unreviewed_runtime_adds_an_independent_failure(complete_baseline_report, field, value):
    baseline = m.validate_result(deepcopy(complete_baseline_report))
    complete_baseline_report["engine"][field] = value
    problems = m.validate_result(complete_baseline_report)
    assert set(problems) - set(baseline)


@pytest.mark.parametrize("field,value", [
    ("networks_attempted", 7), ("networks_attempted", 8.0),
    ("queries_attempted", 7), ("queries_attempted", 8.0),
    ("walking_queries_attempted", 1), ("walking_queries_attempted", False),
    ("native_transit_router_modified", True), ("native_transit_router_modified", 0),
    ("transit_itinerary_serialization_used", True),
    ("fixed_artificial_access_egress_costs", False), ("fixed_artificial_access_egress_costs", 1),
    ("interstop_transfer_model", "unchanged street graph"),
    ("physical_walking_validated", True), ("physical_walking_validated", 0),
    ("request_source_sha256", {}),
])
def test_provenance_and_artificial_model_scope_are_required(complete_baseline_report, field, value):
    baseline = m.validate_result(deepcopy(complete_baseline_report))
    complete_baseline_report[field] = value
    assert set(m.validate_result(complete_baseline_report)) - set(baseline)


def test_worker_uses_isolated_bounded_child_and_parent_validates_result(monkeypatch, tmp_path):
    validated = []
    payload = {"status": "completed", "marker": "untrusted worker evidence"}

    def run(command, **kwargs):
        assert command == [sys.executable, "-I", "-B", str(m.WORKER)]
        assert kwargs["cwd"] == tmp_path
        assert kwargs["shell"] is False and kwargs["check"] is False
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["stderr"] == subprocess.STDOUT
        assert kwargs["timeout"] == 240
        assert kwargs["env"]["TEMP"] == str(tmp_path / "tmp")
        (tmp_path / "worker-result.json").write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    def reject(report):
        validated.append(report.copy())
        return ["Independent oracle rejected the native result"]

    monkeypatch.setattr(m.runner.subprocess, "run", run)
    monkeypatch.setattr(m, "validate_result", reject)
    report = m.run_worker(tmp_path)
    assert validated == [payload]
    assert report["status"] == "failed"
    assert "Independent oracle rejected the native result" in report["problems"]


def test_missing_mixed_chain_exits_as_failure_even_with_successful_worker(monkeypatch, tmp_path, complete_baseline_report):
    def run(command, **kwargs):
        (tmp_path / "worker-result.json").write_text(json.dumps(complete_baseline_report), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(m.runner.subprocess, "run", run)
    result = m.run_worker(tmp_path)
    assert result["status"] == "failed"
    assert result["cases_passed"] == 7
    assert result["same_day_control_passed"] is True


@pytest.mark.parametrize("payload", [None, "{", "[]", "null", '{"x": NaN}', '{"x": Infinity}', '{"x": 1e999}'])
def test_malformed_nonfinite_or_missing_worker_json_is_rejected(monkeypatch, tmp_path, payload):
    def run(command, **kwargs):
        if payload is not None:
            (tmp_path / "worker-result.json").write_text(payload, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(m.runner.subprocess, "run", run)
    result = m.run_worker(tmp_path)
    assert result["status"] == "failed"
    assert result["problems"]


def test_oversized_worker_json_is_rejected_before_decode(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "REPORT_LIMIT_BYTES", 16)

    def run(command, **kwargs):
        (tmp_path / "worker-result.json").write_bytes(b" " * 17)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(m.runner.subprocess, "run", run)
    report = m.run_worker(tmp_path)
    assert report["status"] == "failed"
    assert "exceeds" in " ".join(report["problems"])


def test_nonzero_exit_and_timeout_cannot_be_reported_as_passed(monkeypatch, tmp_path):
    def failed_run(command, **kwargs):
        (tmp_path / "worker-result.json").write_text('{"status":"completed"}', encoding="utf-8")
        return subprocess.CompletedProcess(command, 7)

    monkeypatch.setattr(m.runner.subprocess, "run", failed_run)
    monkeypatch.setattr(m, "validate_result", lambda report: [])
    report = m.run_worker(tmp_path)
    assert report["status"] == "failed"
    assert "code 7" in " ".join(report["problems"])
    (tmp_path / "worker.log").unlink()

    def timed_out(command, **kwargs):
        kwargs["stdout"].write(b"native transfer query did not finish\n")
        kwargs["stdout"].flush()
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(m.runner.subprocess, "run", timed_out)
    report = m.run_worker(tmp_path)
    assert report["status"] == "failed"
    assert "exceeded" in " ".join(report["problems"])
    assert "native transfer query did not finish" in report["worker_log_tail"]


def test_stages_only_separate_fixed_cases_and_preserves_diagnostic_scope(monkeypatch, fake_inputs):
    originals = {p: p.read_bytes() for p in (fake_inputs.jar, fake_inputs.street)}

    def run(work):
        assert work.parent == fake_inputs.work_root
        assert work.name.startswith("homereach-service-day-transfer-")
        assert not work.is_relative_to(fake_inputs.checkout)
        assert (work / m.smoke.ENGINE_NAME).read_bytes() == originals[fake_inputs.jar]
        assert (work / "streets.osm.pbf").read_bytes() == originals[fake_inputs.street]
        assert {p.name for p in work.glob("*.gtfs.zip")} == {case["id"] + ".gtfs.zip" for case in m.fixture.CASES}
        worker.verify_inputs(work)
        return accepted_process_stub(work)

    monkeypatch.setattr(m, "run_worker", run)
    report = m.inspect_service_day_transfers(fake_inputs.jar, fake_inputs.work_root)
    assert report["status"] == "passed", report["problems"]
    assert report["stage"] == "synthetic_service_day_transfer_baseline"
    assert report["native_state_diagnostic_only"] is True
    assert report["routing_ready"] is report["production_correction"] is False
    assert report["fixed_fixture_walking_correction"] is report["date_service_projection_used"] is False
    assert report["uncorrected_current_date_baseline"] is True
    assert report["real_project_datasets_read"] == report["melbourne_journeys_computed"] == 0
    assert report["temporary_workspace_created"] is report["temporary_workspace_removed"] is True
    assert report["protected_inputs_unchanged"] is True
    assert len(report["fixture_sha256"]) == 10
    assert report["execution_source_sha256"] == m._source_hashes()
    assert all(path.read_bytes() == value for path, value in originals.items())
    assert_clean(fake_inputs)


def test_worker_cannot_replace_scope_or_provenance(monkeypatch, fake_inputs):
    monkeypatch.setattr(m, "run_worker", lambda work: {
        "status": "passed", "problems": [], "routing_ready": True,
        "production_correction": True, "native_state_diagnostic_only": False,
        "date_service_projection_used": True, "uncorrected_current_date_baseline": False,
        "stage": "production", "real_project_datasets_read": 7,
        "execution_source_sha256": {"forged": "hash"}, "case_definitions": ["forged"],
    })
    report = m.inspect_service_day_transfers(fake_inputs.jar, fake_inputs.work_root)
    assert report["status"] == "failed"
    assert report["routing_ready"] is report["production_correction"] is False
    assert report["native_state_diagnostic_only"] is True
    assert report["date_service_projection_used"] is False
    assert report["uncorrected_current_date_baseline"] is True
    assert report["stage"] == "synthetic_service_day_transfer_baseline"
    assert report["real_project_datasets_read"] == 0
    assert report["execution_source_sha256"] == m._source_hashes()
    assert report["case_definitions"] != ["forged"]
    assert "parent metadata" in " ".join(report["problems"])
    assert_clean(fake_inputs)


@pytest.mark.parametrize("name", ["jar", "streets.osm.pbf"] + [c["id"] + ".gtfs.zip" for c in m.fixture.CASES])
def test_every_staged_input_is_rechecked(monkeypatch, fake_inputs, name):
    def run(work):
        (work / (m.smoke.ENGINE_NAME if name == "jar" else name)).write_bytes(b"changed")
        return accepted_process_stub(work)

    monkeypatch.setattr(m, "run_worker", run)
    report = m.inspect_service_day_transfers(fake_inputs.jar, fake_inputs.work_root)
    assert report["status"] == "failed"
    assert report["protected_inputs_unchanged"] is True
    assert "staged input changed" in " ".join(report["problems"])
    assert_clean(fake_inputs)


@pytest.mark.parametrize("target", ["jar", "street", "source"])
def test_protected_inputs_and_sources_are_rechecked(monkeypatch, fake_inputs, target):
    path = fake_inputs.checkout / m.SOURCE_PATHS[0] if target == "source" else getattr(fake_inputs, target)

    def run(work):
        path.write_bytes(path.read_bytes() + b"\nchanged")
        return accepted_process_stub(work)

    monkeypatch.setattr(m, "run_worker", run)
    report = m.inspect_service_day_transfers(fake_inputs.jar, fake_inputs.work_root)
    assert report["status"] == "failed"
    assert report["protected_inputs_unchanged"] is False
    assert_clean(fake_inputs)


def test_missing_runtime_blocks_before_engine_or_fixture_read(monkeypatch, tmp_path):
    monkeypatch.setattr(m.runtime, "inspect_runtime", lambda: {"blockers": ["missing runtime"]})
    monkeypatch.setattr(m.smoke, "check_engine", lambda path: pytest.fail("engine must not be read"))
    monkeypatch.setattr(m, "run_worker", lambda work: pytest.fail("worker must not start"))
    report = m.inspect_service_day_transfers(tmp_path / "missing.jar", tmp_path / "missing-work")
    assert report["status"] == "blocked"
    assert report["temporary_workspace_created"] is False
    assert report["problems"] == ["missing runtime"]


def test_cleanup_failure_remains_failed(monkeypatch, fake_inputs):
    created = []

    class LeakyWorkspace:
        def __init__(self, *, prefix, dir):
            self.path = Path(dir) / (prefix + "controlled-leak")

        def __enter__(self):
            self.path.mkdir()
            created.append(self.path)
            return str(self.path)

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(m.runner.tempfile, "TemporaryDirectory", LeakyWorkspace)
    monkeypatch.setattr(m, "run_worker", accepted_process_stub)
    try:
        report = m.inspect_service_day_transfers(fake_inputs.jar, fake_inputs.work_root)
        assert report["status"] == "failed"
        assert report["temporary_workspace_removed"] is False
        assert "cleanup" in " ".join(report["problems"]).lower()
    finally:
        for path in created:
            shutil.rmtree(path)
    assert_clean(fake_inputs)


class NativeList(list):
    def get(self, index):
        return self[index]

    def add(self, value):
        self.append(value)

    def size(self):
        return len(self)


def native_transfer_example():
    return SimpleNamespace(
        stopIdForIndex=NativeList(["fixture:TRANSFER_A", "fixture:TRANSFER_B", "fixture:TRANSFER_C"]),
        streetTransfers=NativeList([NativeList([1, 12000]), NativeList([0, 12000, 2, 20000]), NativeList([1, 20000])]),
    )


@pytest.mark.parametrize("query_raises", [False, True])
def test_empty_transfer_scope_restores_original_object_on_success_and_failure(query_raises):
    transit = native_transfer_example()
    original = transit.streetTransfers
    before = worker.transfer_inventory(transit)
    audit = None
    try:
        with worker.same_stop_transfer_model(transit, NativeList, NativeList) as audit:
            assert transit.streetTransfers is not original
            assert all(not row["transfers"] for row in worker.transfer_inventory(transit))
            if query_raises:
                raise RuntimeError("native query failed")
    except RuntimeError as error:
        assert query_raises and str(error) == "native query failed"
    assert transit.streetTransfers is original
    assert worker.transfer_inventory(transit) == before
    assert audit["applied"] is audit["restored"] is True
    assert audit["original"] == audit["after"] == before
    assert audit["scoped"] == audit["scoped_after"]


def test_invalid_scoped_inventory_cannot_prevent_original_object_restoration():
    transit = native_transfer_example()
    original = transit.streetTransfers
    with pytest.raises(ValueError, match="Malformed"):
        with worker.same_stop_transfer_model(transit, NativeList, NativeList):
            transit.streetTransfers[0].append(1)
    assert transit.streetTransfers is original


@pytest.mark.parametrize("bad_values", [[1], [3, 10], [-1, 10], [1, -10], None])
def test_malformed_native_transfer_inventory_is_rejected(bad_values):
    transit = native_transfer_example()
    transit.streetTransfers[0] = None if bad_values is None else NativeList(bad_values)
    with pytest.raises(ValueError, match="Malformed|Invalid"):
        worker.transfer_inventory(transit)


def test_worker_rejects_modified_timetable_before_engine_import(monkeypatch, fake_inputs):
    work = fake_inputs.work_root / "stage"
    work.mkdir()
    shutil.copyfile(fake_inputs.jar, work / m.smoke.ENGINE_NAME)
    shutil.copyfile(fake_inputs.street, work / "streets.osm.pbf")
    for case in m.fixture.CASES:
        m.fixture.write_gtfs(work / (case["id"] + ".gtfs.zip"), case)
    worker.verify_inputs(work)
    case = m.fixture.CASES[-1]
    tables = m.fixture.gtfs_tables(case)
    with ZipFile(work / (case["id"] + ".gtfs.zip"), "w") as archive:
        for name, value in tables.items():
            archive.writestr(name, value + (b"\n" if name == "stop_times.txt" else b""))
    with pytest.raises(ValueError, match="differs"):
        worker.verify_inputs(work)


@pytest.mark.parametrize("status,code", [("passed", 0), ("blocked", 2), ("failed", 1)])
def test_cli_preserves_json_status_and_exit_code(monkeypatch, capsys, status, code):
    report = {"status": status, "problems": []}
    monkeypatch.setattr(m, "inspect_service_day_transfers", lambda jar, work: report)
    assert m.main(["--jar", "reviewed.jar", "--work-root", "outside", "--json"]) == code
    assert json.loads(capsys.readouterr().out) == report
