"""Shared process and input lifecycle for bounded synthetic routing diagnostics.

Each caller supplies its worker, independent validator, fixture writer and
execution-source inventory. The helper owns process isolation, trusted parent
metadata, immutable input checks and cleanup; it does not interpret journeys.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

import run_routing_smoke_test as smoke


def execution_source_hashes(root: Path, paths: Sequence[str]) -> dict[str, str]:
    """Normalize only text newlines so Windows and Linux source identities agree."""
    return {name: hashlib.sha256((root / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for name in paths}


def _invoke_worker(work: Path, worker_path: Path, timeout_seconds: int) -> int:
    with (work / "worker.log").open("xb") as output:
        process = subprocess.run(
            [sys.executable, "-I", "-B", str(worker_path)], cwd=work,
            env=smoke.child_environment(work), stdin=subprocess.DEVNULL,
            stdout=output, stderr=subprocess.STDOUT, shell=False, check=False,
            timeout=timeout_seconds,
        )
    return process.returncode


def _read_worker_report(work: Path, limit_bytes: int) -> dict:
    result_path = work / "worker-result.json"
    if result_path.stat().st_size > limit_bytes:
        raise ValueError("Worker report exceeds the fixed experiment limit.")
    result = json.loads(result_path.read_text(encoding="utf-8"),
                        parse_constant=smoke.finite_json_number, parse_float=smoke.finite_json_number)
    if not isinstance(result, dict):
        raise ValueError("Worker report must be an object.")
    return result


def run_worker(work: Path, *, worker_path: Path, timeout_seconds: int,
               report_limit_bytes: int, validator: Callable[[dict], list[str]]) -> dict:
    """Run one isolated child and derive status from its independently checked data."""
    try:
        returncode = _invoke_worker(work, worker_path, timeout_seconds)
    except subprocess.TimeoutExpired:
        return {"status": "failed", "problems": [f"Worker exceeded {timeout_seconds} seconds."],
                "worker_log_tail": smoke.read_log_tail(work / "worker.log")}
    try:
        result = _read_worker_report(work, report_limit_bytes)
        problems = validator(result)
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as error:
        result, problems = {}, [f"Cannot validate worker report: {error}"]
    if returncode:
        problems.append(f"Worker exited with code {returncode}.")
    result["status"] = "failed" if problems else "passed"
    result["problems"] = problems
    if problems:
        result["worker_log_tail"] = smoke.read_log_tail(work / "worker.log")
    return result


def _stage_inputs(work: Path, jar: Path,
                  fixture_writer: Callable[[Path], Sequence[str]]) -> dict[str, str]:
    """Stage reviewed bytes plus caller-defined exclusive synthetic fixtures."""
    for directory in ("config", "cache", "tmp"):
        (work / directory).mkdir()
    copies = {smoke.ENGINE_NAME: jar, "streets.osm.pbf": smoke.STREET_FIXTURE}
    for name, source in copies.items():
        shutil.copyfile(source, work / name)
    smoke.check_engine(work / smoke.ENGINE_NAME)
    fixture_names = tuple(fixture_writer(work))
    if (any(not isinstance(name, str) or not name or Path(name).name != name
            or "/" in name or "\\" in name or name in copies for name in fixture_names)
            or len(fixture_names) != len(set(fixture_names))):
        raise ValueError("Fixture writer returned duplicate or invalid staged filenames.")
    return {name: smoke.sha256(work / name) for name in (*copies, *fixture_names)}


def _merge_worker_evidence(parent: dict, child: dict) -> None:
    """A child cannot replace the parent's scope, provenance or cleanup facts."""
    reserved = parent.keys() - {"status", "problems"}
    collisions = sorted(reserved & child.keys())
    parent.update({key: value for key, value in child.items() if key not in reserved})
    if collisions:
        _fail(parent, "Worker attempted to replace parent metadata: " + ", ".join(collisions))


def _fail(report: dict, message: str) -> None:
    report["status"] = "failed"
    report["problems"].append(message)


def _verify_cleanup(report: dict, work: Path | None) -> None:
    if work is None:
        return
    report["temporary_workspace_removed"] = not work.exists()
    if not report["temporary_workspace_removed"]:
        _fail(report, "Temporary workspace cleanup did not complete.")


def _verify_originals(report: dict, originals: dict[Path, str], sources: dict | None,
                      source_hashes: Callable[[], dict]) -> None:
    if not originals:
        return
    try:
        unchanged = all(smoke.sha256(path) == digest for path, digest in originals.items())
        unchanged = unchanged and source_hashes() == sources
        report["protected_inputs_unchanged"] = unchanged
        if not unchanged:
            _fail(report, "An original input or execution source changed.")
    except OSError as error:
        _fail(report, f"Cannot recheck original inputs: {error}")


def inspect_diagnostic(jar: Path, work_root: Path, *, metadata: dict,
                       runtime_inventory: Callable[[], dict],
                       workspace_prefix: str,
                       fixture_writer: Callable[[Path], Sequence[str]],
                       source_hashes: Callable[[], dict],
                       execute_worker: Callable[[Path], dict]) -> dict:
    """Own the lifecycle while callers retain their fixed scientific contract."""
    started = time.monotonic()
    report = {
        "schema_version": 1, "status": "blocked", "synthetic_fixture_only": True,
        "real_project_datasets_read": 0, "melbourne_journeys_computed": 0,
        "routing_ready": False, "temporary_workspace_created": False,
        "temporary_workspace_removed": True, "protected_inputs_unchanged": None,
        "problems": [], "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        **metadata,
    }
    report["runtime_inventory"] = runtime_inventory()
    if report["runtime_inventory"]["blockers"]:
        report["problems"] = report["runtime_inventory"]["blockers"]
        return report
    originals, sources, work = {}, None, None
    try:
        jar = jar.resolve()
        smoke.check_engine(jar)
        work_root = smoke.check_work_root(work_root)
        if smoke.sha256(smoke.STREET_FIXTURE) != smoke.STREET_SHA256:
            raise ValueError("Reviewed street fixture fingerprint mismatch.")
        originals = {jar: smoke.sha256(jar), smoke.STREET_FIXTURE: smoke.STREET_SHA256}
        sources = source_hashes()
        report["execution_source_sha256"] = sources
        with tempfile.TemporaryDirectory(prefix=workspace_prefix, dir=work_root) as directory:
            work = Path(directory).resolve()
            report["temporary_workspace_created"] = True
            staged = _stage_inputs(work, jar, fixture_writer)
            report["fixture_sha256"] = staged
            _merge_worker_evidence(report, execute_worker(work))
            if any(smoke.sha256(work / name) != digest for name, digest in staged.items()):
                _fail(report, "A staged input changed during the experiment.")
    except (OSError, ValueError) as error:
        report["status"] = "failed" if report["temporary_workspace_created"] else "blocked"
        report["problems"].append(str(error))
    finally:
        _verify_cleanup(report, work)
        _verify_originals(report, originals, sources, source_hashes)
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return report
