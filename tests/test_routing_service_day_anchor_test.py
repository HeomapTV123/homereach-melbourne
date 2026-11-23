"""The native anchor probe's process boundary preserves scope and evidence."""
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

import pytest

from test_routing_service_day_anchor import valid_report as native_pair_examples


ROOT = Path(__file__).resolve().parents[1]


def load_script(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    old_path = sys.path.copy()
    old_bytecode = sys.dont_write_bytecode
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = old_path
        sys.dont_write_bytecode = old_bytecode
    return module


m = load_script("routing_anchor_parent_under_test", "run_routing_service_day_anchor_test.py")
worker = load_script("routing_anchor_worker_under_test", "_routing_service_day_anchor_worker.py")


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


def passed_worker(work):
    return {"status": "passed", "problems": []}


@pytest.fixture
def complete_report():
    # Only the previously reviewed direct WALK and scope audits are reused.
    # Native timetable states come from independently hand-declared examples.
    previous = json.loads((ROOT / "docs/evidence/routing_walk_correction_linux_2026-11-18.json").read_text())
    report = native_pair_examples()
    report.update({key: deepcopy(previous[key]) for key in ("engine", "walking_correction", "walking")})
    report["engine"]["network_timezone"] = "Australia/Melbourne"
    report.update(status="completed", queries_attempted=14, walking_queries_attempted=1,
                  walking_crs="EPSG:4326", native_transit_router_modified=False,
                  transit_itinerary_serialization_used=False,
                  request_source_sha256={
                      "r5/regional_task.py": "2cb5729eb461fc66d7e482f833373121e87e8b21cc68f81f46cc4d5ea8be6876",
                      "r5/trip_planner.py": "541bcf3ec644bb717195518699ad540d1c448330539e26b1f36cd850ff7674a7",
                  })
    return report


def test_complete_native_pair_evidence_is_accepted_without_changing_raw_states(complete_report):
    before = deepcopy(complete_report["pairs"])
    assert m.validate_result(complete_report) == []
    assert complete_report["pairs_passed"] == 7
    assert complete_report["pairs"] == before


@pytest.mark.parametrize("field,value", [("r5py", "1.1.8"), ("sha256", "0" * 64),
                                          ("jvm_started", False), ("classpath_verified", 1),
                                          ("network_timezone", "UTC"), ("python_routing_jobs", 2),
                                          ("max_heap_bytes", 1073741825), ("max_heap_bytes", True),
                                          ("java_version", "17.0.9")])
def test_unreviewed_runtime_or_unbounded_execution_cannot_pass(complete_report, field, value):
    complete_report["engine"][field] = value
    assert m.validate_result(complete_report)


@pytest.mark.parametrize("field,value", [("queries_attempted", 13), ("queries_attempted", 14.0),
                                          ("walking_queries_attempted", 0), ("walking_queries_attempted", True),
                                          ("native_transit_router_modified", True), ("native_transit_router_modified", 0),
                                          ("transit_itinerary_serialization_used", True),
                                          ("transit_itinerary_serialization_used", 0),
                                          ("request_source_sha256", {}),
                                          ("request_source_sha256", {"r5/regional_task.py": "0" * 64})])
def test_execution_provenance_and_native_only_scope_are_required(complete_report, field, value):
    complete_report[field] = value
    assert m.validate_result(complete_report)


@pytest.mark.parametrize("scope", ["index", "origin", "geometry"])
def test_each_scoped_correction_must_restore(complete_report, scope):
    complete_report["walking_correction"][scope]["restored"] = False
    assert m.validate_result(complete_report)


@pytest.mark.parametrize("change", ["missing", "extra", "wrong_crs", "wrong_identity", "wrong_endpoint", "off_path", "coherent_wrong_distance", "wrong_duration"])
def test_independent_walk_control_checks_actual_path_and_costs(complete_report, change):
    walk = complete_report["walking"][0]
    if change == "missing":
        complete_report["walking"] = []
    elif change == "extra":
        complete_report["walking"].append(deepcopy(walk))
    elif change == "wrong_crs":
        complete_report["walking_crs"] = "EPSG:3857"
    elif change == "wrong_identity":
        walk["to_id"] = "somewhere_else"
    elif change == "wrong_endpoint":
        walk["geometry"]["coordinates"][0][0] += 0.001
    elif change == "off_path":
        walk["geometry"]["coordinates"].insert(1, [0.012, 0.020])
    elif change == "coherent_wrong_distance":
        # A plausible speed alone must not allow an unrelated walking distance.
        walk["distance_m"] = 1000.0
        walk["travel_time_seconds"] = 1000.0
    else:
        walk["travel_time_seconds"] += 120
    assert m.validate_result(complete_report)


def test_raw_native_back_chain_is_copied_in_forward_order():
    def state(time, back=None):
        return SimpleNamespace(time=time, boardTime=-1, pattern=-1, trip=-1, round=0,
                               stop=0, boardStopPosition=-1, alightStopPosition=-1,
                               accessMode="WALK", egressMode=None, back=back)
    first = state(90012)
    second = state(90600, first)
    final = state(90612, second)
    snapshot = worker.native_state_chain(final)
    assert [s["time"] for s in snapshot] == [90012, 90600, 90612]
    first.time = 1
    final.back = None
    assert [s["time"] for s in snapshot] == [90012, 90600, 90612]


def test_native_back_pointer_cycle_is_bounded():
    state = SimpleNamespace(time=90000, boardTime=-1, pattern=-1, trip=-1, round=0,
                            stop=0, boardStopPosition=-1, alightStopPosition=-1,
                            accessMode="WALK", egressMode=None)
    state.back = state
    with pytest.raises(ValueError, match="bound"):
        worker.native_state_chain(state)


def test_worker_uses_isolated_bounded_child_and_parent_validates_result(monkeypatch, tmp_path):
    validated = []
    payload = {"status": "completed", "marker": "untrusted worker evidence"}

    def run(command, **kwargs):
        assert command == [sys.executable, "-I", "-B", str(m.WORKER)]
        assert kwargs["cwd"] == tmp_path
        assert kwargs["shell"] is False and kwargs["check"] is False
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["stderr"] == subprocess.STDOUT
        assert kwargs["timeout"] == m.TIMEOUT_SECONDS
        assert kwargs["env"]["TEMP"] == str(tmp_path / "tmp")
        (tmp_path / "worker-result.json").write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    def reject(report):
        validated.append(report.copy())
        return ["Independent oracle rejected the native result"]

    monkeypatch.setattr(m.subprocess, "run", run)
    monkeypatch.setattr(m, "validate_result", reject)
    report = m.run_worker(tmp_path)
    assert validated == [payload]
    assert report["status"] == "failed"
    assert "Independent oracle rejected the native result" in report["problems"]


@pytest.mark.parametrize("payload", [None, "{", "[]", "null", '{"x": NaN}', '{"x": Infinity}', '{"x": 1e999}'])
def test_malformed_nonfinite_or_missing_worker_json_is_rejected(monkeypatch, tmp_path, payload):
    def run(command, **kwargs):
        if payload is not None:
            (tmp_path / "worker-result.json").write_text(payload, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(m.subprocess, "run", run)
    result = m.run_worker(tmp_path)
    assert result["status"] == "failed"
    assert result["problems"]


def test_oversized_worker_json_is_rejected_before_decode(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "REPORT_LIMIT_BYTES", 16)

    def run(command, **kwargs):
        (tmp_path / "worker-result.json").write_bytes(b" " * 17)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(m.subprocess, "run", run)
    result = m.run_worker(tmp_path)
    assert result["status"] == "failed"
    assert "exceeds" in " ".join(result["problems"])


def test_successful_oracle_cannot_hide_nonzero_process_exit(monkeypatch, tmp_path):
    def run(command, **kwargs):
        (tmp_path / "worker-result.json").write_text('{"status":"completed"}', encoding="utf-8")
        return subprocess.CompletedProcess(command, 7)

    monkeypatch.setattr(m.subprocess, "run", run)
    monkeypatch.setattr(m, "validate_result", lambda report: [])
    report = m.run_worker(tmp_path)
    assert report["status"] == "failed"
    assert "code 7" in " ".join(report["problems"])


def test_timeout_preserves_failure_and_native_log_tail(monkeypatch, tmp_path):
    def run(command, **kwargs):
        kwargs["stdout"].write(b"anchor query failed to finish\n")
        kwargs["stdout"].flush()
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(m.subprocess, "run", run)
    report = m.run_worker(tmp_path)
    assert report["status"] == "failed"
    assert "exceeded" in " ".join(report["problems"])
    assert "anchor query failed to finish" in report["worker_log_tail"]


def test_validated_child_stages_only_owned_files_and_keeps_diagnostic_scope(monkeypatch, fake_inputs):
    originals = {p: p.read_bytes() for p in (fake_inputs.jar, fake_inputs.street)}

    def run(work):
        assert work.parent == fake_inputs.work_root
        assert work.name.startswith("homereach-service-day-anchor-")
        assert not work.is_relative_to(fake_inputs.checkout)
        assert (work / m.smoke.ENGINE_NAME).read_bytes() == originals[fake_inputs.jar]
        assert (work / "streets.osm.pbf").read_bytes() == originals[fake_inputs.street]
        assert (work / "service-day.gtfs.zip").is_file()
        return passed_worker(work)

    monkeypatch.setattr(m, "run_worker", run)
    report = m.inspect_service_day_anchors(fake_inputs.jar, fake_inputs.work_root)
    assert report["status"] == "passed", report["problems"]
    assert report["stage"] == "synthetic_service_day_anchor_probe"
    assert report["native_state_diagnostic_only"] is True
    assert report["routing_ready"] is report["production_correction"] is False
    assert report["real_project_datasets_read"] == report["melbourne_journeys_computed"] == 0
    assert report["temporary_workspace_created"] is report["temporary_workspace_removed"] is True
    assert report["protected_inputs_unchanged"] is True
    assert report["execution_source_sha256"] == m._source_hashes()
    assert all(path.read_bytes() == value for path, value in originals.items())
    assert_clean(fake_inputs)


def test_worker_cannot_claim_production_readiness_or_replace_provenance(monkeypatch, fake_inputs):
    monkeypatch.setattr(m, "run_worker", lambda work: {
        "status": "passed", "problems": [], "routing_ready": True,
        "production_correction": True, "native_state_diagnostic_only": False,
        "stage": "production", "real_project_datasets_read": 7,
        "execution_source_sha256": {"forged": "hash"}, "pair_cases": ["forged cases"],
    })
    report = m.inspect_service_day_anchors(fake_inputs.jar, fake_inputs.work_root)
    assert report["status"] == "failed"
    assert report["routing_ready"] is report["production_correction"] is False
    assert report["native_state_diagnostic_only"] is True
    assert report["stage"] == "synthetic_service_day_anchor_probe"
    assert report["real_project_datasets_read"] == 0
    assert report["execution_source_sha256"] == m._source_hashes()
    assert report["pair_cases"] != ["forged cases"]
    assert "parent metadata" in " ".join(report["problems"])
    assert_clean(fake_inputs)


@pytest.mark.parametrize("name", ["jar", "streets.osm.pbf", "service-day.gtfs.zip"])
def test_mutated_staged_input_prevents_success(monkeypatch, fake_inputs, name):
    def run(work):
        (work / (m.smoke.ENGINE_NAME if name == "jar" else name)).write_bytes(b"changed")
        return passed_worker(work)

    monkeypatch.setattr(m, "run_worker", run)
    report = m.inspect_service_day_anchors(fake_inputs.jar, fake_inputs.work_root)
    assert report["status"] == "failed"
    assert report["protected_inputs_unchanged"] is True
    assert "staged input changed" in " ".join(report["problems"])
    assert_clean(fake_inputs)


@pytest.mark.parametrize("target", ["jar", "street", "source"])
def test_mutated_protected_input_or_execution_source_prevents_success(monkeypatch, fake_inputs, target):
    path = fake_inputs.checkout / m.SOURCE_PATHS[0] if target == "source" else getattr(fake_inputs, target)

    def run(work):
        path.write_bytes(path.read_bytes() + b"\nchanged")
        return passed_worker(work)

    monkeypatch.setattr(m, "run_worker", run)
    report = m.inspect_service_day_anchors(fake_inputs.jar, fake_inputs.work_root)
    assert report["status"] == "failed"
    assert report["protected_inputs_unchanged"] is False
    assert_clean(fake_inputs)


def test_missing_runtime_blocks_before_any_engine_or_fixture_read(monkeypatch, tmp_path):
    monkeypatch.setattr(m.runtime, "inspect_runtime", lambda: {"blockers": ["missing runtime"]})
    monkeypatch.setattr(m.smoke, "check_engine", lambda path: pytest.fail("engine must not be read"))
    monkeypatch.setattr(m, "run_worker", lambda work: pytest.fail("worker must not start"))
    report = m.inspect_service_day_anchors(tmp_path / "missing.jar", tmp_path / "missing-work")
    assert report["status"] == "blocked"
    assert report["temporary_workspace_created"] is False
    assert report["problems"] == ["missing runtime"]


def test_cleanup_failure_remains_a_failure(monkeypatch, fake_inputs):
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

    monkeypatch.setattr(m.tempfile, "TemporaryDirectory", LeakyWorkspace)
    monkeypatch.setattr(m, "run_worker", passed_worker)
    try:
        report = m.inspect_service_day_anchors(fake_inputs.jar, fake_inputs.work_root)
        assert report["status"] == "failed"
        assert report["temporary_workspace_removed"] is False
        assert "cleanup" in " ".join(report["problems"]).lower()
    finally:
        for path in created:
            shutil.rmtree(path)
    assert_clean(fake_inputs)


@pytest.mark.parametrize("status,code", [("passed", 0), ("blocked", 2), ("failed", 1)])
def test_cli_keeps_json_status_and_exit_code(monkeypatch, capsys, status, code):
    report = {"status": status, "problems": []}
    monkeypatch.setattr(m, "inspect_service_day_anchors", lambda jar, work: report)
    assert m.main(["--jar", "reviewed.jar", "--work-root", "outside", "--json"]) == code
    assert json.loads(capsys.readouterr().out) == report
