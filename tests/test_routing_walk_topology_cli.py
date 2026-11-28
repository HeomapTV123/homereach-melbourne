"""CLI failure paths use synthetic Osmium output; no Melbourne snapshots required."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_routing_walk_topology.py"
spec = importlib.util.spec_from_file_location("topology_cli_audit", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

ROWS = (
    "w10 v1 dV Thighway=footway Nn1,n2\n"
    "w11 v1 dV Thighway=steps Nn2,n20\n"
    "w12 v1 dV Thighway=path Nn20,n21\n"
)


class FakeProcess:
    def __init__(self, output, exit_code=0):
        self.stdout = io.StringIO(output)
        self.returncode = None
        self.exit_code = exit_code
        self.closed = False
        self.killed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.stdout.close()
        self.closed = True
        self.wait()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = self.exit_code
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9


@pytest.fixture
def project(tmp_path):
    config = tmp_path / "config" / "routing_walk_topology_review.json"
    source = tmp_path / "data" / "interim" / "routing" / "fixture.osm.pbf"
    config.parent.mkdir()
    source.parent.mkdir(parents=True)
    source.write_bytes(b"synthetic PBF bytes; Osmium is mocked by these tests")
    config.write_text(json.dumps({
        "schema_version": 1,
        "source_pbf": source.relative_to(tmp_path).as_posix(),
        "source_osm_sha256": "1" * 64,
        "source_osm_snapshot_utc": "2026-10-01T20:22:06Z",
        "locations": [
            {"id": "orig_footscray", "node_id": 2},
            {"id": "orig_dandenong", "node_id": 21},
            {"id": "dest_flinders", "node_id": None},
        ],
    }), encoding="utf-8")
    return tmp_path, config, source


def install_osmium(monkeypatch, outputs=(ROWS,), exit_codes=None, on_start=None):
    processes = []
    calls = []
    codes = exit_codes or [0] * len(outputs)

    def popen(command, **kwargs):
        number = len(calls)
        calls.append((command, kwargs))
        if on_start is not None:
            on_start(number)
        process = FakeProcess(outputs[number], codes[number])
        processes.append(process)
        return process

    monkeypatch.setattr(m.subprocess, "Popen", popen)
    return calls, processes


def boundary_args(root):
    return [
        "--project-root", str(root), "--boundary-locations",
        "orig_footscray", "orig_dandenong",
    ]


def printed_report(output):
    start = output.index("{")
    report, _ = json.JSONDecoder().raw_decode(output[start:])
    return report


def file_contents(root):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def assert_no_completed_report(captured):
    assert "Files written: 0 | Journeys computed: 0" not in captured.out
    assert '"strict_audit"' not in captured.out
    assert '"counts"' not in captured.out


def test_default_cli_preserves_single_pass_strict_report(project, monkeypatch, capsys):
    root, _, source = project
    before = file_contents(root)
    calls, processes = install_osmium(monkeypatch)

    assert m.main(["--project-root", str(root)]) == 0
    captured = capsys.readouterr()
    report = printed_report(captured.out)

    assert report["counts"] == {"ways_seen": 3, "ways_included": 2, "ways_excluded": 1}
    assert [r.get("component_nodes") for r in report["results"]] == [2, 2, None]
    assert "strict_audit" not in report
    assert len(calls) == 1
    assert calls[0][0][0:2] == ["osmium", "cat"]
    assert calls[0][0][-1] == str(source)
    assert calls[0][1].get("shell", False) is False
    assert calls[0][1].get("stderr") != m.subprocess.PIPE
    assert all(p.closed for p in processes)
    assert file_contents(root) == before


def test_boundary_cli_is_two_pass_and_read_only(project, monkeypatch, capsys):
    root, _, source = project
    before = file_contents(root)
    calls, processes = install_osmium(monkeypatch, (ROWS, ROWS))

    assert m.main(boundary_args(root)) == 0
    report = printed_report(capsys.readouterr().out)

    assert report["strict_audit"]["counts"]["ways_seen"] == 3
    assert [r.get("component_nodes") for r in report["strict_audit"]["results"]] == [2, 2, None]
    assert report["source"] == {
        "path": source.relative_to(root).as_posix(),
        "bytes": len(source.read_bytes()),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "unchanged_during_audit": True,
        "expected_derived_sha256": None,
    }
    assert len(calls) == 2
    assert all(command[0] == "osmium" for command, _ in calls)
    assert all(kwargs.get("shell", False) is False for _, kwargs in calls)
    assert all(kwargs.get("stderr") != m.subprocess.PIPE for _, kwargs in calls)
    assert all(p.closed for p in processes)
    assert file_contents(root) == before


@pytest.mark.parametrize("failing_pass", [0, 1])
def test_osmium_failure_never_publishes_a_completed_report(
    project, monkeypatch, capsys, failing_pass
):
    root, _, _ = project
    before = file_contents(root)
    codes = [0, 0]
    codes[failing_pass] = 1
    calls, processes = install_osmium(monkeypatch, (ROWS, ROWS), exit_codes=codes)

    assert m.main(boundary_args(root)) == 2
    captured = capsys.readouterr()

    assert_no_completed_report(captured)
    assert "osmium" in captured.err.lower()
    assert len(calls) == failing_pass + 1
    assert all(p.closed for p in processes)
    assert file_contents(root) == before


def test_missing_osmium_explains_environment_without_a_report(project, monkeypatch, capsys):
    root, _, _ = project

    def missing(*_, **__):
        raise FileNotFoundError("osmium unavailable")

    monkeypatch.setattr(m.subprocess, "Popen", missing)
    assert m.main(boundary_args(root)) == 2
    captured = capsys.readouterr()

    assert_no_completed_report(captured)
    assert "homereach-osm" in captured.err


def test_changed_pbf_between_passes_invalidates_report(project, monkeypatch, capsys):
    root, _, source = project

    def change_source(number):
        if number == 1:
            source.write_bytes(b"a different snapshot")

    install_osmium(monkeypatch, (ROWS, ROWS), on_start=change_source)
    assert m.main(boundary_args(root)) == 2
    captured = capsys.readouterr()

    assert_no_completed_report(captured)
    assert "chang" in captured.err.lower()


def test_changed_way_stream_invalidates_report(project, monkeypatch, capsys):
    root, _, _ = project
    install_osmium(monkeypatch, (ROWS, ROWS.replace("Nn2,n20", "Nn2,n99")))

    assert m.main(boundary_args(root)) == 2
    assert_no_completed_report(capsys.readouterr())


def test_malformed_way_aborts_boundary_review(project, monkeypatch, capsys):
    root, _, _ = project
    calls, processes = install_osmium(monkeypatch, (ROWS + "w99 Thighway=footway Nninvalid\n",))

    assert m.main(boundary_args(root)) == 2
    assert_no_completed_report(capsys.readouterr())
    assert len(calls) == 1
    assert all(p.closed for p in processes)
    assert processes[0].killed


@pytest.mark.parametrize("escape", ["config", "source"])
def test_paths_outside_project_are_rejected_before_osmium(project, monkeypatch, capsys, escape):
    root, config, _ = project
    outside = root.parent / "outside-fixture"
    outside.write_bytes(b"outside the selected project")
    args = boundary_args(root)
    if escape == "config":
        args += ["--config", str(outside)]
    else:
        data = json.loads(config.read_text(encoding="utf-8"))
        data["source_pbf"] = str(outside)
        config.write_text(json.dumps(data), encoding="utf-8")
    calls, _ = install_osmium(monkeypatch)

    assert m.main(args) == 2
    assert calls == []
    assert_no_completed_report(capsys.readouterr())


@pytest.mark.parametrize("extra", [
    ["--osmium", "untrusted-program"],
    ["--boundary-limit", "0"],
    ["--boundary-limit", "-1"],
])
def test_invalid_cli_options_do_not_start_osmium(project, monkeypatch, capsys, extra):
    root, _, _ = project
    calls, _ = install_osmium(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        m.main(["--project-root", str(root), *extra])

    assert exc.value.code == 2
    assert calls == []
    assert_no_completed_report(capsys.readouterr())


def test_unknown_location_does_not_start_osmium(project, monkeypatch, capsys):
    root, _, _ = project
    calls, _ = install_osmium(monkeypatch)

    assert m.main(["--project-root", str(root), "--boundary-locations", "unknown_station"]) == 2
    assert calls == []
    assert_no_completed_report(capsys.readouterr())
