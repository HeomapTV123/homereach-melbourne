"""Runtime inventory uses metadata and a bounded Java version probe, not R5."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import subprocess
import sys
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_routing_runtime.py"
spec = importlib.util.spec_from_file_location("routing_runtime_inventory", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.fixture
def baseline(monkeypatch, tmp_path):
    executable = tmp_path / "jdk" / ("java.exe" if os.name == "nt" else "java")
    monkeypatch.setattr(m.sys, "version_info", (3, 12, 14))
    monkeypatch.setattr(m.struct, "calcsize", lambda _: 8)
    monkeypatch.setenv("CONDA_PREFIX", sys.prefix)
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "homereach-routing")
    monkeypatch.setattr(m.metadata, "version", lambda name: "1.1.7" if name == "r5py" else "1.0")
    monkeypatch.setattr(m, "find_java", lambda: executable)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "", 'openjdk version "21.0.9" 2025-10-21\nOpenJDK 64-Bit Server VM\n')

    monkeypatch.setattr(m.subprocess, "run", run)
    return executable, calls


@pytest.mark.parametrize("text,expected", [
    ('openjdk version "21.0.9" 2025-10-21', 21),
    ('java version "21"', 21),
    ('openjdk 21.0.1 2023-10-17', 21),
    ('java version "1.8.0_402"', 8),
    ('openjdk version "17.0.9"', 17),
    ('openjdk version "22-ea"', 22),
    ('Java diagnostic: 21 installations', None),
    ('java version "not-a-version"', None),
    ('java version "21bogus"', None),
    ('', None),
])
def test_java_version_parsing(text, expected):
    assert m.java_major_version(text) == expected


def test_passed_inventory_keeps_engine_and_routing_unverified(baseline, monkeypatch, capsys):
    executable, calls = baseline
    for variable in ("JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS"):
        monkeypatch.setenv(variable, "-javaagent:unexpected.jar")
    assert m.main(["--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "prerequisites_passed"
    assert report["routing_engine_imported"] is False
    assert report["embedded_jvm_started"] is False
    assert report["journeys_computed"] == 0
    assert "Embedded JVM and R5 JAR compatibility" in report["not_tested"]
    command, options = calls[0]
    assert command == [str(executable), "-version"]
    assert options["shell"] is False
    assert options["stdin"] == subprocess.DEVNULL
    assert options["timeout"] == 10
    assert all(name not in options["env"] for name in ("JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS"))
    assert os.environ["JAVA_TOOL_OPTIONS"] == "-javaagent:unexpected.jar"


@pytest.mark.parametrize("missing", ["r5py", "jpype1", "geopandas"])
def test_missing_package_is_actionable_and_not_a_failed_dataset(baseline, monkeypatch, capsys, missing):
    def version(name):
        if name == missing:
            raise m.metadata.PackageNotFoundError(name)
        return "1.1.7" if name == "r5py" else "1.0"

    monkeypatch.setattr(m.metadata, "version", version)
    assert m.main(["--json"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["packages"][missing]["status"] == "missing"
    assert f"Missing Python package: {missing}." in report["blockers"]
    assert "-n homereach-routing" in report["next_check_command"]


@pytest.mark.parametrize("failure,status", [
    (FileNotFoundError("Java vanished"), "execution_error"),
    (PermissionError("Java is not executable"), "execution_error"),
    (subprocess.TimeoutExpired(["java", "-version"], 10), "timeout"),
])
def test_java_probe_failures_return_blocked_reports(baseline, monkeypatch, capsys, failure, status):
    def fail(*_, **__):
        raise failure

    monkeypatch.setattr(m.subprocess, "run", fail)
    assert m.main(["--json"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["java"]["status"] == status
    assert report["java"]["major_version"] is None


def test_java_timeout_is_explained_in_beginner_text_output(baseline, monkeypatch, capsys):
    def timeout(*_, **__):
        raise subprocess.TimeoutExpired(["java", "-version"], 10)

    monkeypatch.setattr(m.subprocess, "run", timeout)
    assert m.main([]) == 2
    assert "Java detail: java -version exceeded 10 seconds." in capsys.readouterr().out


@pytest.mark.parametrize("output,returncode,status", [
    ('unrecognised Java runtime', 0, "unreadable_version"),
    ('openjdk version "21.0.9"', 1, "execution_error"),
])
def test_java_output_never_overrides_a_failed_process(baseline, monkeypatch, output, returncode, status):
    monkeypatch.setattr(m.subprocess, "run", lambda command, **_: subprocess.CompletedProcess(command, returncode, "", output))
    report = m.inspect_runtime()
    assert report["status"] == "blocked"
    assert report["java"]["status"] == status


def test_missing_java_does_not_run_a_process(baseline, monkeypatch):
    _, calls = baseline
    monkeypatch.setattr(m, "find_java", lambda: None)
    report = m.inspect_runtime()
    assert report["java"]["status"] == "missing"
    assert report["status"] == "blocked"
    assert calls == []


@pytest.mark.parametrize("change", ["python", "r5py", "java", "bits", "conda_prefix"])
def test_different_baselines_require_review_not_an_incompatibility_claim(baseline, monkeypatch, tmp_path, change):
    if change == "python":
        monkeypatch.setattr(m.sys, "version_info", (3, 13, 1))
    elif change == "r5py":
        monkeypatch.setattr(m.metadata, "version", lambda _: "9.0")
    elif change == "java":
        monkeypatch.setattr(m.subprocess, "run", lambda command, **_: subprocess.CompletedProcess(command, 0, "", 'openjdk version "25.0.1"'))
    elif change == "bits":
        monkeypatch.setattr(m.struct, "calcsize", lambda _: 4)
    else:
        monkeypatch.setenv("CONDA_PREFIX", str(tmp_path / "different-environment"))
    report = m.inspect_runtime()
    assert report["status"] == "blocked"
    assert len(report["blockers"]) == 1
    assert "incompatible" not in report["blockers"][0]


def test_empty_package_metadata_is_not_treated_as_installed(baseline, monkeypatch):
    monkeypatch.setattr(m.metadata, "version", lambda name: "" if name == "r5py" else "1.0")
    report = m.inspect_runtime()
    assert report["packages"]["r5py"]["status"] == "unreadable_metadata"
    assert report["status"] == "blocked"


def test_lookup_excludes_current_directory_relative_entries_and_checkout(tmp_path, monkeypatch):
    current = tmp_path / "working"
    trusted = tmp_path / "installed-jdk" / "bin"
    checkout = tmp_path / "checkout"
    for directory in (current, trusted, checkout):
        directory.mkdir(parents=True)
        executable = directory / ("java.exe" if os.name == "nt" else "java")
        executable.write_bytes(b"placeholder; never executed")
        executable.chmod(0o755)
    monkeypatch.chdir(current)
    monkeypatch.setattr(m, "ROOT", checkout)
    monkeypatch.setenv("PATH", os.pathsep.join(["", ".", "relative", str(current), str(checkout), str(trusted)]))
    assert m.find_java() == (trusted / ("java.exe" if os.name == "nt" else "java")).resolve()


def test_fresh_cli_never_imports_engines_or_reads_project_data(tmp_path):
    # Installed-looking metadata cannot trigger a module import. No project input
    # paths are provided, and every nonstandard runtime import is denied.
    metadata_root = tmp_path / "package-metadata"
    metadata_root.mkdir()
    for name in m.DISTRIBUTIONS:
        directory = metadata_root / f"{name}-1.1.7.dist-info"
        directory.mkdir()
        (directory / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.1.7\n", encoding="utf-8")
    runner = """
import sys, runpy
sys.dont_write_bytecode = True
script, metadata_root = sys.argv[1:]
sys.path.insert(0, metadata_root)
class DenyRuntimeImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'r5py', 'jpype', 'geopandas', 'pandas', 'numpy', 'shapely', 'pyproj', 'rasterio'}:
            raise AssertionError('Runtime import attempted: ' + fullname)
sys.meta_path.insert(0, DenyRuntimeImports())
sys.argv = [script, '--json']
runpy.run_path(script, run_name='__main__')
"""
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = subprocess.run(
        [sys.executable, "-S", "-c", runner, str(SCRIPT), str(metadata_root)],
        cwd=tmp_path, capture_output=True, text=True, timeout=30, check=False,
        env={**os.environ, "PATH": str(tmp_path / "no-java"), "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 2
    assert result.stderr == ""
    report = json.loads(result.stdout)
    assert all(package["status"] == "installed" for package in report["packages"].values())
    assert report["java"]["status"] == "missing"
    assert report["project_datasets_read"] == 0
    after = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before


def test_cli_has_no_arbitrary_executable_or_path_option(capsys):
    with pytest.raises(SystemExit) as error:
        m.main(["--java", "some-program"])
    assert error.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


@pytest.mark.parametrize("prefix,windows,expected", [
    (PureWindowsPath(r"D:\My Tools\envs\HoMeReAcH-RoUtInG"), True,
     'conda run --no-capture-output --prefix "D:\\My Tools\\envs\\HoMeReAcH-RoUtInG" '
     'python scripts/check_routing_runtime.py'),
    (PurePosixPath("/mnt/data/owner's envs/homereach-routing"), False,
     "conda run --no-capture-output --prefix '/mnt/data/owner'\"'\"'s envs/homereach-routing' "
     "python scripts/check_routing_runtime.py"),
    (PureWindowsPath(r"C:\Users\PhamDang\anaconda3"), True,
     "conda run --no-capture-output -n homereach-routing python scripts/check_routing_runtime.py"),
    (PurePosixPath("/opt/conda/envs/homereach"), False,
     "conda run --no-capture-output -n homereach-routing python scripts/check_routing_runtime.py"),
])
def test_check_hint_preserves_routing_prefix_and_quotes_for_the_target_shell(prefix, windows, expected):
    assert m.check_command(prefix, windows=windows) == expected


@pytest.mark.parametrize("as_json", [False, True])
def test_relocated_environment_hint_reaches_cli_output(baseline, monkeypatch, tmp_path, capsys, as_json):
    prefix = tmp_path / "custom envs" / "homereach-routing"
    # Replace this module's sys binding, without changing the interpreter's sys.prefix.
    monkeypatch.setattr(m, "sys", SimpleNamespace(
        prefix=str(prefix), version_info=(3, 12, 14), executable=str(prefix / "python"),
    ))
    monkeypatch.setenv("CONDA_PREFIX", str(prefix))
    monkeypatch.setattr(m, "find_java", lambda: None)
    quote = '"' if os.name == "nt" else "'"
    expected = (f"conda run --no-capture-output --prefix {quote}{prefix}{quote} "
                "python scripts/check_routing_runtime.py")
    assert m.main(["--json"] if as_json else []) == 2
    output = capsys.readouterr().out
    if as_json:
        report = json.loads(output)
        assert report["next_check_command"] == expected
        assert report["java"]["status"] == "missing"
    else:
        assert f"Check that environment: {expected}" in output
        assert "Setup and storage recovery: docs/commute_routing_runtime.md" in output
        assert "conda env create -f" not in output
