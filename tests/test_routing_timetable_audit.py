"""Pinned audit integration uses fictional nested feeds and real hash checks."""
from __future__ import annotations

import builtins
import csv
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import socket
import sqlite3
import subprocess
import sys
import warnings
from zipfile import ZipFile

import pytest

from homereach.routing import preflight, timetable_audit as audit
from homereach.transport.gtfs import DAYS


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = Path("data/raw/transport/gtfs.zip")


def csv_text(header, rows=()):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue()


def source_tables(*, exceptions=False):
    return {
        "agency.txt": csv_text(["agency_id", "agency_timezone"], [["agency", "Australia/Melbourne"]]),
        "routes.txt": csv_text(
            ["route_id", "agency_id", "route_short_name", "route_long_name", "route_type"],
            [["route", "agency", "Fictional", "Test service", "3"]]),
        "trips.txt": csv_text(["trip_id", "route_id", "service_id"],
                              [["active", "route", "weekday"], ["off", "route", "inactive"]]),
        "calendar.txt": csv_text(["service_id", *DAYS, "start_date", "end_date"],
                                  [["weekday", *["1"] * 7, "20261001", "20261031"],
                                   ["inactive", *["0"] * 7, "20261001", "20261031"]]),
        "calendar_dates.txt": csv_text(["service_id", "date", "exception_type"],
                                        [["weekday", "20261013", "2"],
                                         ["inactive", "20261013", "1"]] if exceptions else []),
        "stops.txt": csv_text(
            ["stop_id", "stop_name", "stop_lat", "stop_lon", "location_type", "parent_station", "wheelchair_boarding"],
            [["a", "First", "-37.8", "144.9", "0", "", ""],
             ["b", "Second", "-37.81", "144.91", "", "", ""]]),
        "stop_times.txt": csv_text(
            ["trip_id", "stop_id", "stop_sequence", "arrival_time", "departure_time"],
            [["off", "b", "10", "25:05:00", "25:05:00"],
             ["active", "a", "0", "07:00:00", "07:00:00"],
             ["off", "a", "0", "24:55:00", "24:55:00"],
             ["active", "b", "10", "07:10:00", "07:10:00"]]),
    }


def tree(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() if path.is_file() else None
            for path in root.rglob("*")}


@pytest.fixture
def project(tmp_path):
    project = tmp_path / "project"
    (project / "config").mkdir(parents=True)
    for name in ("routing_pilot.json", "gtfs_snapshot.json"):
        (project / "config" / name).write_bytes((ROOT / "config" / name).read_bytes())
    return project


@pytest.fixture(autouse=True)
def forbid_engine_network_and_extraction(monkeypatch):
    original = builtins.__import__

    def guard(name, *args, **kwargs):
        if name.split(".")[0] in {"r5py", "jpype", "jnius", "geopandas", "pyogrio"}:
            raise AssertionError("A timetable audit must not initialize a routing/GIS runtime.")
        return original(name, *args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("No network or extracted project files in this audit.")

    monkeypatch.setattr(builtins, "__import__", guard)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(ZipFile, "extract", forbidden)
    monkeypatch.setattr(ZipFile, "extractall", forbidden)


def install(project, monkeypatch, *, transform=None, exceptions=False,
            duplicate_inner=False, extra_outer=False):
    snapshot_path = project / "config/gtfs_snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    archive = project / ARCHIVE
    archive.parent.mkdir(parents=True)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Duplicate name:", category=UserWarning)
        with ZipFile(archive, "w") as outer:
            for member in snapshot["outer_members"]:
                tables = source_tables(exceptions=exceptions)
                if transform:
                    transform(tables)
                buffer = io.BytesIO()
                with ZipFile(buffer, "w") as inner:
                    for name, text in tables.items():
                        inner.writestr(name, text)
                    if duplicate_inner:
                        inner.writestr("trips.txt", tables["trips.txt"])
                outer.writestr(member, buffer.getvalue())
            if extra_outer:
                outer.writestr("unreviewed.txt", "unexpected")
    snapshot.update(sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                    active_trip_counts={f: 1 for f in ("2", "3", "4")},
                    replacement_trip_counts={f: 0 for f in ("2", "3", "4")},
                    location_counts={f: 2 for f in ("2", "3", "4")},
                    platform_counts={f: 2 for f in ("2", "3", "4")},
                    scan_rows={f: 4 for f in ("2", "3", "4")})
    snapshot["expected_totals"].update(source_rows=12, active_events=6)
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    # Only fictional snapshot selection is replaced. Archive identities, row
    # scans, calendar selection, CSV and reference checks remain real.
    loader = lambda path: json.loads(Path(path).read_text(encoding="utf-8"))
    monkeypatch.setattr(preflight, "load_transport_snapshot", loader)
    monkeypatch.setattr(audit, "load_transport_snapshot", loader)
    return snapshot


def run(project, tmp_path):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    before = tree(project)
    progress = []
    report = audit.audit_routing_timetable(project, work_root=work, progress=progress.append)
    assert tree(project) == before
    assert list(work.iterdir()) == []
    assert report["temporary_workspace_removed"] is True
    assert report["project_files_written"] == report["journeys_computed"] == 0
    assert report["routing_ready"] is False
    json.dumps(report, allow_nan=False)
    return report, progress


def test_missing_original_archive_blocks_without_temporary_files(project, tmp_path):
    report, _ = run(project, tmp_path)
    assert report["status"] == "blocked"
    assert report["scan_complete"] is False
    assert report["temporary_workspace_created"] is False
    assert report["protected_inputs_unchanged"] is True


@pytest.mark.parametrize("exceptions", [False, True])
def test_complete_multifeed_scan_is_scoped_by_feed_and_calendar(project, tmp_path, monkeypatch, exceptions):
    install(project, monkeypatch, exceptions=exceptions)
    report, messages = run(project, tmp_path)
    assert report["status"] == "passed", report
    assert report["scan_complete"] is True
    assert report["rows_scanned"] == 12
    assert report["active_rows_scanned"] == 6
    assert report["protected_inputs_unchanged"] is True
    assert [f["feed_id"] for f in report["feeds"]] == ["2", "3", "4"]
    assert all(f["active_rows_with_extended_times"] == (2 if exceptions else 0) for f in report["feeds"])
    assert any("Feed 4" in message for message in messages)


def test_hash_mismatch_refuses_nested_read(project, tmp_path, monkeypatch):
    install(project, monkeypatch)
    with (project / ARCHIVE).open("ab") as stream:
        stream.write(b"changed")
    monkeypatch.setattr(audit, "_nested_feed", lambda *args: pytest.fail("Mismatched source was opened."))
    report, _ = run(project, tmp_path)
    assert report["status"] == "invalid"
    assert report["temporary_workspace_created"] is False
    assert "fingerprint" in " ".join(report["errors"])


@pytest.mark.parametrize("fault", ["duplicate_inner", "extra_outer"])
def test_archive_inventory_faults_fail_closed(project, tmp_path, monkeypatch, fault):
    install(project, monkeypatch, **{fault: True})
    report, _ = run(project, tmp_path)
    assert report["status"] == "invalid"
    assert report["scan_complete"] is False


def test_header_only_frequency_table_is_unsupported_not_invalid(project, tmp_path, monkeypatch):
    install(project, monkeypatch, transform=lambda t:
            t.update({"frequencies.txt": "trip_id,start_time,end_time,headway_secs,exact_times\n"}))
    report, _ = run(project, tmp_path)
    assert report["status"] == "blocked"
    assert report["scan_complete"] is True
    assert not report["errors"]
    assert all(any(i["code"] == "unsupported_frequency_table" for i in f["issues"]) for f in report["feeds"])


def test_route_continuous_defaults_reach_core(project, tmp_path, monkeypatch):
    def edit(tables):
        tables["routes.txt"] = csv_text(
            ["route_id", "agency_id", "route_short_name", "route_long_name", "route_type", "continuous_pickup"],
            [["route", "agency", "Fictional", "Test", "3", "0"]])
    install(project, monkeypatch, transform=edit)
    report, _ = run(project, tmp_path)
    assert report["status"] == "blocked"
    assert all(f["effective_continuous_service_rows"] == 4 for f in report["feeds"])


@pytest.mark.parametrize("table,change", [
    ("trips.txt", lambda value: value.replace("active,route,weekday", "active,missing,weekday")),
    ("stops.txt", lambda value: value.replace("stop_id,stop_name", "stop_id,stop_id")),
    ("agency.txt", lambda value: value.replace("Australia/Melbourne", "UTC")),
    ("stop_times.txt", lambda value: value + '"unterminated'),
])
def test_bad_tables_are_invalid_and_cleanup(project, tmp_path, monkeypatch, table, change):
    install(project, monkeypatch, transform=lambda t: t.__setitem__(table, change(t[table])))
    report, _ = run(project, tmp_path)
    assert report["status"] == "invalid"
    assert report["scan_complete"] is False
    assert report["errors"]


@pytest.mark.parametrize("field", ["scan_rows", "active_trip_counts", "platform_counts"])
def test_pinned_count_mismatch_is_invalid(project, tmp_path, monkeypatch, field):
    install(project, monkeypatch)
    path = project / "config/gtfs_snapshot.json"
    snapshot = json.loads(path.read_text())
    snapshot[field]["2"] += 1
    path.write_text(json.dumps(snapshot))
    report, _ = run(project, tmp_path)
    assert report["status"] == "invalid"


def test_real_contract_refuses_fictional_fingerprint(project, tmp_path, monkeypatch):
    with monkeypatch.context() as patch:
        install(project, patch)
    report, _ = run(project, tmp_path)
    assert report["status"] == "invalid"
    assert "Transport contract changed" in " ".join(report["errors"])
    assert report["temporary_workspace_created"] is False


def test_work_root_inside_project_is_rejected(project, monkeypatch):
    install(project, monkeypatch)
    before = tree(project)
    report = audit.audit_routing_timetable(project, work_root=project)
    assert report["status"] == "invalid"
    assert tree(project) == before


def test_work_root_symlink_into_project_is_rejected(project, tmp_path, monkeypatch):
    install(project, monkeypatch)
    alias = tmp_path / "work-link"
    try:
        alias.symlink_to(project, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Directory symlinks are unavailable in this test environment.")
    before = tree(project)
    report = audit.audit_routing_timetable(project, work_root=alias)
    assert report["status"] == "invalid"
    assert report["temporary_workspace_created"] is False
    assert tree(project) == before


@pytest.mark.parametrize("status", ["error", "unexpected"])
def test_unexpected_feed_status_never_passes(project, tmp_path, monkeypatch, status):
    install(project, monkeypatch)
    original = audit.audit_stop_times
    def unexpected_status(*args, **kwargs):
        result = original(*args, **kwargs)
        result["status"] = status
        return result
    monkeypatch.setattr(audit, "audit_stop_times", unexpected_status)
    report, _ = run(project, tmp_path)
    assert report["status"] == "error"
    assert report["errors"]


def test_unhandled_small_table_column_collision_is_processing_error(project, tmp_path, monkeypatch):
    def edit(tables):
        tables["trips.txt"] = csv_text(
            ["trip_id", "route_id", "service_id", "route_type"],
            [["active", "route", "weekday", "3"], ["off", "route", "inactive", "3"]])
    install(project, monkeypatch, transform=edit)
    report, _ = run(project, tmp_path)
    assert report["status"] == "error"
    assert report["scan_complete"] is False
    assert any("Internal timetable processing failed" in message for message in report["errors"])


def test_small_table_header_control_is_invalid(project, tmp_path, monkeypatch):
    def edit(tables):
        tables["agency.txt"] = csv_text(
            ["agency_id", "agency_timezone", "extra\tfield"],
            [["agency", "Australia/Melbourne", "value"]])
    install(project, monkeypatch, transform=edit)
    report, _ = run(project, tmp_path)
    assert report["status"] == "invalid"
    assert any("control character in header" in message for message in report["errors"])


@pytest.mark.parametrize("relative", [ARCHIVE, Path("config/routing_pilot.json"), Path("config/gtfs_snapshot.json")])
def test_mutation_during_audit_never_passes(project, tmp_path, monkeypatch, relative):
    install(project, monkeypatch)
    original = audit.audit_stop_times
    calls = 0
    def modify_after_read(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 1:
            with (project / relative).open("ab") as handle:
                handle.write(b" ")
        return result
    monkeypatch.setattr(audit, "audit_stop_times", modify_after_read)
    work = tmp_path / "work"
    work.mkdir()
    report = audit.audit_routing_timetable(project, work_root=work)
    assert report["status"] == "invalid"
    assert report["protected_inputs_unchanged"] is False
    assert report["temporary_workspace_removed"] is True
    assert not list(work.iterdir())


@pytest.mark.parametrize("failure", [OSError(errno.ENOSPC, "No space left"), sqlite3.OperationalError("disk full")])
def test_operational_scan_failure_is_not_invalid_data(project, tmp_path, monkeypatch, failure):
    install(project, monkeypatch)
    def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr(audit, "audit_stop_times", fail)
    report, _ = run(project, tmp_path)
    assert report["status"] == "error"
    assert report["scan_complete"] is False
    assert report["protected_inputs_unchanged"] is True


def test_recheck_read_error_does_not_claim_input_mutation(project, tmp_path, monkeypatch):
    install(project, monkeypatch)
    original = audit.sha256_file
    seen = 0
    def unreadable_on_recheck(path):
        nonlocal seen
        if Path(path) == project / ARCHIVE:
            seen += 1
            if seen == 2:
                raise PermissionError("Input became unreadable")
        return original(path)
    monkeypatch.setattr(audit, "sha256_file", unreadable_on_recheck)
    report, _ = run(project, tmp_path)
    assert report["status"] == "error"
    assert report["protected_inputs_unchanged"] is None
    assert not any("changed during" in message for message in report["errors"])


def test_cli_json_missing_archive_and_unused_runtime_imports(project):
    bootstrap = """
import importlib.abc, runpy, sys
class RejectRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'geopandas','pyogrio','pyproj','shapely','r5py','jpype','jnius'}:
            raise AssertionError('Unused runtime import: ' + fullname)
sys.meta_path.insert(0, RejectRuntime())
script, *arguments = sys.argv[1:]
sys.argv = [script, *arguments]
runpy.run_path(script, run_name='__main__')
"""
    before = tree(project)
    result = subprocess.run(
        [sys.executable, "-c", bootstrap, str(ROOT / "scripts/audit_routing_timetable.py"),
         "--project-root", str(project), "--json"],
        text=True, capture_output=True, timeout=30, check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "blocked"
    assert "Verifying" in result.stderr
    assert tree(project) == before


def test_cli_full_fictional_scan_has_clean_json_and_live_progress(project, tmp_path, monkeypatch, capsys):
    install(project, monkeypatch)
    work = tmp_path / "work"
    work.mkdir()
    before = tree(project)
    script = ROOT / "scripts/audit_routing_timetable.py"
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    monkeypatch.setattr(sys, "argv", [str(script), "--project-root", str(project),
                                     "--work-root", str(work), "--json"])
    namespace = runpy.run_path(str(script), run_name="timetable_cli_tests")
    exit_code = namespace["main"]()
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert exit_code == 0
    assert report["status"] == "passed"
    assert report["rows_scanned"] == 12
    assert "Feed 4:" in captured.err
    assert tree(project) == before
    assert not list(work.iterdir())


@pytest.mark.parametrize("dependency", ["numpy", "pandas"])
def test_cli_missing_dependency_returns_json_error(project, dependency):
    bootstrap = """
import importlib.util, runpy, sys
dependency, script, *arguments = sys.argv[1:]
original = importlib.util.find_spec
importlib.util.find_spec = lambda name, *args, **kwargs: None if name == dependency else original(name, *args, **kwargs)
sys.argv = [script, *arguments]
runpy.run_path(script, run_name='__main__')
"""
    result = subprocess.run(
        [sys.executable, "-c", bootstrap, dependency, str(ROOT / "scripts/audit_routing_timetable.py"),
         "--project-root", str(project), "--json"],
        text=True, capture_output=True, timeout=30, check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert result.returncode == 1, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "environment_error"
    assert dependency in report["error"]
    assert "homereach" in report["hint"]
