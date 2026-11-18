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
        "itinerary_mode": "upstream",
        "engine": {
            "sha256": m.ENGINE_SHA256, "r5py": "1.1.7", "java_version": "21.0.10",
            "jvm_started": True, "max_heap_bytes": 1_073_741_824,
            "classpath_verified": True, "temporary_directory_verified": True,
            "python_routing_jobs": 1,
        },
        "walking": [leg("WALK", "2026-10-13T08:00:00", 2646, 2646)],
        "transit": [leg("WALK", "2026-10-13T08:00:00", 11, 11), bus,
                    leg("WALK", "2026-10-13T08:11:00", 11, 11, segment=2)],
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
    assert m.single_bus_diagnostics(report["transit"]) == {
        "options_checked": 60, "unexpected_leg_sequences": 0,
        "egress_padding_mismatches": 53,
    }


def test_late_shared_egress_is_rejected_even_without_an_overlap(completed_report):
    completed_report["transit"][2]["departure_time"] = "2026-10-13T08:21:00"
    assert m.timeline_diagnostics(completed_report["transit"])["overlaps"] == 0
    assert m.timeline_diagnostics(completed_report["transit"])["wait_mismatches"] == 0
    assert m.single_bus_diagnostics(completed_report["transit"])["egress_padding_mismatches"] == 1
    assert any("egress failed" in problem for problem in m.validate_outcomes(completed_report))


@pytest.mark.parametrize("missing_segment", [0, 1, 2])
def test_every_option_requires_access_bus_and_egress(completed_report, missing_segment):
    incomplete = deepcopy(completed_report["transit"])
    for row in incomplete:
        row["option"] = 1
    del incomplete[missing_segment]
    completed_report["transit"].extend(incomplete)
    assert any("complete WALK, BUS, WALK" in problem for problem in m.validate_outcomes(completed_report))


@pytest.mark.parametrize("egress,expected", [
    ("2026-10-13T08:10:59", 0), ("2026-10-13T08:11:01", 0),
    ("2026-10-13T08:10:58", 1), ("2026-10-13T08:11:02", 1),
])
def test_pinned_egress_padding_allows_only_one_second_rounding(completed_report, egress, expected):
    completed_report["transit"][2]["departure_time"] = egress
    before = deepcopy(completed_report["transit"])
    assert m.single_bus_diagnostics(before)["egress_padding_mismatches"] == expected
    assert before == completed_report["transit"]


def isolated_report(completed_report):
    report = deepcopy(completed_report)
    report["itinerary_mode"] = "isolated_legs"
    report["itinerary_adapter"] = {
        "name": m.leg_isolation.ADAPTER_NAME, "version": 1, "r5py": "1.1.7",
        "source_sha256": dict(m.leg_isolation.SOURCE_SHA256),
        "applied": True, "restored": True, "legs_snapshotted": 3,
    }
    return report


@pytest.mark.parametrize("change", ["wrong_mode", "missing_audit", "wrong_source", "not_applied",
                                   "not_restored", "no_snapshots", "boolean_count",
                                   "numeric_applied", "numeric_restored", "boolean_version"])
def test_requested_adapter_requires_a_complete_audit(completed_report, change):
    report = isolated_report(completed_report)
    assert m.validate_integration(report, True) == []
    if change == "wrong_mode":
        report["itinerary_mode"] = "upstream"
    elif change == "missing_audit":
        del report["itinerary_adapter"]
    elif change == "wrong_source":
        report["itinerary_adapter"]["source_sha256"]["r5/trip_leg.py"] = "0" * 64
    elif change == "not_applied":
        report["itinerary_adapter"]["applied"] = False
    elif change == "not_restored":
        report["itinerary_adapter"]["restored"] = False
    elif change == "no_snapshots":
        report["itinerary_adapter"]["legs_snapshotted"] = 0
    elif change == "numeric_applied":
        report["itinerary_adapter"]["applied"] = 1
    elif change == "numeric_restored":
        report["itinerary_adapter"]["restored"] = 1
    elif change == "boolean_version":
        report["itinerary_adapter"]["version"] = True
    else:
        report["itinerary_adapter"]["legs_snapshotted"] = True
    assert m.validate_integration(report, True)


def test_upstream_mode_refuses_an_undeclared_adapter(completed_report):
    report = isolated_report(completed_report)
    report["itinerary_mode"] = "upstream"
    assert m.validate_integration(completed_report, False) == []
    assert m.validate_integration(report, False)


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

    def worker(work, *, isolate_legs, check_walking_geometry, correct_walking_paths):
        assert isolate_legs is False
        assert check_walking_geometry is False
        assert correct_walking_paths is False
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


def test_explicit_adapter_flag_reaches_worker_and_raw_rows_are_kept(tmp_path, monkeypatch, completed_report):
    worker_report = isolated_report(completed_report)

    def run(command, **_):
        assert command == [sys.executable, "-I", "-B", str(m.WORKER), "--isolate-itinerary-legs"]
        (tmp_path / "worker-result.json").write_text(json.dumps(worker_report), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(m.subprocess, "run", run)
    report = m.run_worker(tmp_path, isolate_legs=True)
    assert report["status"] == "passed"
    assert report["transit"] == worker_report["transit"]
    assert report["single_bus_diagnostics"] == {
        "options_checked": 1, "unexpected_leg_sequences": 0, "egress_padding_mismatches": 0,
    }


def test_requested_adapter_cannot_silently_run_upstream(tmp_path, monkeypatch, completed_report):
    def run(command, **_):
        (tmp_path / "worker-result.json").write_text(json.dumps(completed_report), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(m.subprocess, "run", run)
    report = m.run_worker(tmp_path, isolate_legs=True)
    assert report["status"] == "failed"
    assert any("integration mode" in problem for problem in report["problems"])


def geometric_report(completed_report):
    report = deepcopy(completed_report)
    report["geometry_crs"] = {"walking": "EPSG:4326", "transit": "EPSG:4326", "no_service": "EPSG:4326"}
    for row, points, distance in (
        (report["walking"][0], [[0.0061, 0.018], [0.0299, 0.018]], 2646.439124),
        (report["transit"][0], [[0.0061, 0.018], [0.006, 0.018]], 11.119492),
        (report["transit"][2], [[0.030, 0.018], [0.0299, 0.018]], 11.119492),
    ):
        row["geometry"] = {"type": "LineString", "coordinates": points}
        row["distance_m"] = distance
    report["transit"][1]["geometry"] = {
        "type": "LineString", "coordinates": [[0.006, 0.018], [0.030, 0.018]],
    }
    return report


def corrected_report(completed_report):
    report = geometric_report(isolated_report(completed_report))
    index_source = hashlib.sha256(Path(m.index_correction.__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    report["walking_correction"] = {
        "index": {
            "name": m.index_correction.ADAPTER_NAME, "version": 1,
            "source_sha256": index_source, "engine_sha256": m.ENGINE_SHA256,
            "fixture_xml_sha256": m.index_correction.FIXTURE_XML_SHA256,
            "graph_sha256_before": "a" * 64, "graph_sha256_after": "a" * 64,
            "street_pairs": 84, "connector_pairs": 2,
            "linked_stop_vertices": {"SMOKE_WEST": 49, "SMOKE_EAST": 50},
            "coverage_before": {"edge_points_checked": 420, "missing_edge_candidates": 322},
            "coverage_after": {"edge_points_checked": 420, "missing_edge_candidates": 0},
            "applied": True, "restored": True, "network_unchanged": True,
        },
        "origin": {
            "name": m.origin_correction.ADAPTER_NAME, "version": 1, "r5py": "1.1.7",
            "source_sha256": dict(m.origin_correction.SOURCE_SHA256),
            "applied": True, "restored": True, "routers_created": 3,
            "origins_initialized": 3, "reverse_states_rebuilt": 2, "states_registered": 3,
            "helper_loader_closed": True,
            "helper": {"java_source_sha256": m.origin_correction.JAVA_SOURCE_SHA256,
                       "class_sha256": "b" * 64, "compiler_java_version": "21.0.10",
                       "compiled_in_temporary_workspace": True, "original_jar_sha256": m.ENGINE_SHA256},
        },
        "geometry": {
            "name": m.geometry_correction.ADAPTER_NAME, "version": 1, "r5py": "1.1.7",
            "source_sha256": dict(m.geometry_correction.SOURCE_SHA256),
            "applied": True, "restored": True, "segments_constructed": 3,
            "native_costs_preserved": True,
        },
    }
    return report


@pytest.mark.parametrize("change", [
    "missing_component", "wrong_name", "boolean_version", "numeric_applied", "not_restored",
    "wrong_source", "wrong_helper_source", "different_compiler", "no_reverse_states",
    "no_geometry", "changed_graph", "missing_index_candidate", "wrong_stop_link",
    "wrong_index_source", "boolean_coverage", "geometry_costs_changed",
])
def test_walking_correction_requires_verified_used_and_restored_components(completed_report, change):
    report = corrected_report(completed_report)
    assert m.validate_walking_correction(report, True) == []
    audit = report["walking_correction"]
    if change == "missing_component":
        del audit["index"]
    elif change == "wrong_name":
        audit["origin"]["name"] = "unreviewed"
    elif change == "boolean_version":
        audit["geometry"]["version"] = True
    elif change == "numeric_applied":
        audit["index"]["applied"] = 1
    elif change == "not_restored":
        audit["origin"]["restored"] = False
    elif change == "wrong_source":
        audit["origin"]["source_sha256"] = {}
    elif change == "wrong_helper_source":
        audit["origin"]["helper"]["java_source_sha256"] = "0" * 64
    elif change == "different_compiler":
        audit["origin"]["helper"]["compiler_java_version"] = "17.0.1"
    elif change == "no_reverse_states":
        audit["origin"]["reverse_states_rebuilt"] = 0
    elif change == "no_geometry":
        audit["geometry"]["segments_constructed"] = 0
    elif change == "changed_graph":
        audit["index"]["graph_sha256_after"] = "c" * 64
    elif change == "missing_index_candidate":
        audit["index"]["coverage_after"]["missing_edge_candidates"] = 1
    elif change == "wrong_stop_link":
        audit["index"]["linked_stop_vertices"]["SMOKE_EAST"] = 49
    elif change == "wrong_index_source":
        audit["index"]["source_sha256"] = "0" * 64
    elif change == "boolean_coverage":
        audit["index"]["coverage_after"]["missing_edge_candidates"] = False
    elif change == "geometry_costs_changed":
        audit["geometry"]["native_costs_preserved"] = False
    assert m.validate_walking_correction(report, True)


def test_baseline_run_rejects_an_undeclared_walking_correction(completed_report):
    assert m.validate_walking_correction(completed_report, False) == []
    assert m.validate_walking_correction(corrected_report(completed_report), False)


def test_complete_corrected_run_requires_independent_paths_and_retains_raw_rows(tmp_path, monkeypatch, completed_report):
    worker_report = corrected_report(completed_report)

    def run(command, **_):
        assert command[-3:] == ["--isolate-itinerary-legs", "--check-walking-geometry", "--correct-walking-paths"]
        (tmp_path / "worker-result.json").write_text(json.dumps(worker_report), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(m.subprocess, "run", run)
    report = m.run_worker(tmp_path, isolate_legs=True, check_walking_geometry=True, correct_walking_paths=True)
    assert report["status"] == "passed"
    assert report["walking_geometry_diagnostics"]["status"] == "passed"
    assert report["walking_duration_diagnostics"]["duration_mismatches"] == 0
    assert report["walking_duration_diagnostics"]["walking_legs_checked"] == 3
    assert report["walking"] == worker_report["walking"]
    assert report["transit"] == worker_report["transit"]


def test_correct_geometry_and_distance_cannot_hide_wrong_walking_duration(tmp_path, monkeypatch, completed_report):
    worker_report = corrected_report(completed_report)
    worker_report["transit"][2]["travel_time_seconds"] = 678

    def run(command, **_):
        (tmp_path / "worker-result.json").write_text(json.dumps(worker_report), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(m.subprocess, "run", run)
    report = m.run_worker(tmp_path, isolate_legs=True, check_walking_geometry=True, correct_walking_paths=True)
    assert report["status"] == "failed"
    assert report["walking_geometry_diagnostics"]["status"] == "passed"
    assert report["timeline_diagnostics"]["overlaps"] == 0
    assert report["walking_duration_diagnostics"]["duration_mismatches"] == 1
    assert report["transit"] == worker_report["transit"]


def test_geometry_flag_requests_coordinates_and_checks_analytic_paths(tmp_path, monkeypatch, completed_report):
    worker_report = geometric_report(completed_report)

    def run(command, **_):
        assert command == [sys.executable, "-I", "-B", str(m.WORKER), "--check-walking-geometry"]
        (tmp_path / "worker-result.json").write_text(json.dumps(worker_report), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(m.subprocess, "run", run)
    report = m.run_worker(tmp_path, check_walking_geometry=True)
    assert report["status"] == "passed"
    assert report["walking_geometry_diagnostics"]["status"] == "passed"
    assert report["walking_geometry_diagnostics"]["counts"]["walking_legs_checked"] == 3
    assert report["transit"] == worker_report["transit"]


def test_geometry_check_cannot_pass_with_only_nonempty_geometry_booleans(tmp_path, monkeypatch, completed_report):
    def run(command, **_):
        (tmp_path / "worker-result.json").write_text(json.dumps(completed_report), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(m.subprocess, "run", run)
    report = m.run_worker(tmp_path, check_walking_geometry=True)
    assert report["status"] == "failed"
    assert report["walking_geometry_diagnostics"]["status"] == "failed"
    assert report["transit"] == completed_report["transit"]


def test_known_long_egress_fails_geometry_while_timing_remains_valid(tmp_path, monkeypatch, completed_report):
    worker_report = geometric_report(isolated_report(completed_report))
    egress = worker_report["transit"][2]
    egress.update(distance_m=677.897, travel_time_seconds=678,
                  geometry={"type": "LineString", "coordinates": [[0.030, 0.018], [0.036, 0.018]]})

    def run(command, **_):
        assert command[-2:] == ["--isolate-itinerary-legs", "--check-walking-geometry"]
        (tmp_path / "worker-result.json").write_text(json.dumps(worker_report), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(m.subprocess, "run", run)
    report = m.run_worker(tmp_path, isolate_legs=True, check_walking_geometry=True)
    assert report["status"] == "failed"
    assert report["timeline_diagnostics"]["overlaps"] == 0
    assert report["timeline_diagnostics"]["wait_mismatches"] == 0
    assert report["walking_geometry_diagnostics"]["counts"]["shortest_distance_mismatches"] == 1
    assert report["transit"] == worker_report["transit"]


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
    monkeypatch.setattr(m, "inspect_smoke", lambda *_, **__: report)
    assert m.main(["--jar", "reviewed.jar", "--work-root", "temporary", "--json"]) == code
    captured = capsys.readouterr()
    assert json.loads(captured.out) == report
    assert captured.err == ""


def test_cli_passes_explicit_adapter_choice_to_inspection(monkeypatch, capsys):
    def inspect(jar, work_root, *, isolate_legs, check_walking_geometry, correct_walking_paths):
        assert isolate_legs is True
        assert check_walking_geometry is False
        assert correct_walking_paths is False
        return {"status": "blocked", "problems": ["Synthetic prerequisite failure."]}

    monkeypatch.setattr(m, "inspect_smoke", inspect)
    assert m.main(["--jar", "reviewed.jar", "--work-root", "temporary",
                   "--isolate-itinerary-legs", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"


def test_cli_passes_independent_geometry_choice_to_inspection(monkeypatch, capsys):
    def inspect(jar, work_root, *, isolate_legs, check_walking_geometry, correct_walking_paths):
        assert isolate_legs is True
        assert check_walking_geometry is True
        assert correct_walking_paths is False
        return {"status": "blocked", "problems": ["Synthetic prerequisite failure."]}

    monkeypatch.setattr(m, "inspect_smoke", inspect)
    assert m.main(["--jar", "reviewed.jar", "--work-root", "temporary", "--isolate-itinerary-legs",
                   "--check-walking-geometry", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"


@pytest.mark.parametrize("isolate,geometry", [(False, False), (True, False), (False, True)])
def test_walking_correction_requires_all_independent_checks_before_runtime_access(monkeypatch, isolate, geometry):
    def unexpected_inventory():
        raise AssertionError("An invalid correction request must not reach runtime inspection.")

    monkeypatch.setattr(m.runtime, "inspect_runtime", unexpected_inventory)
    result = m.inspect_smoke(Path("unused.jar"), Path("unused-work"), isolate_legs=isolate,
                             check_walking_geometry=geometry, correct_walking_paths=True)
    assert result["status"] == "blocked"
    assert result["walking_correction_requested"] is True
    assert "requires --isolate-itinerary-legs and --check-walking-geometry" in result["problems"][0]


def test_cli_passes_explicit_walking_correction_with_all_checks(monkeypatch, capsys):
    def inspect(jar, work_root, *, isolate_legs, check_walking_geometry, correct_walking_paths):
        assert (isolate_legs, check_walking_geometry, correct_walking_paths) == (True, True, True)
        return {"status": "blocked", "problems": ["Synthetic prerequisite failure."]}

    monkeypatch.setattr(m, "inspect_smoke", inspect)
    assert m.main(["--jar", "reviewed.jar", "--work-root", "temporary", "--isolate-itinerary-legs",
                   "--check-walking-geometry", "--correct-walking-paths", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"


@pytest.mark.parametrize("malformed_audit", [None, 7, []])
def test_cli_can_display_a_failed_malformed_adapter_report(monkeypatch, capsys, malformed_audit):
    report = {"status": "failed", "problems": ["Malformed adapter audit."],
              "temporary_workspace_removed": True, "itinerary_adapter": malformed_audit}
    monkeypatch.setattr(m, "inspect_smoke", lambda *_, **__: report)
    assert m.main(["--jar", "reviewed.jar", "--work-root", "temporary"]) == 1
    assert "Malformed adapter audit." in capsys.readouterr().out


def test_fresh_help_uses_only_stdlib_and_does_not_write_checkout(tmp_path):
    checkout = tmp_path / "checkout"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    for name in ("run_routing_smoke_test.py", "check_routing_runtime.py", "routing_smoke_fixture.py",
                 "routing_leg_isolation.py", "routing_walk_geometry.py", "routing_street_geometry_correction.py",
                 "routing_street_index_correction.py", "routing_street_origin_correction.py"):
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
