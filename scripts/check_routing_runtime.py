"""Inventory routing prerequisites without importing r5py or building a network."""
from __future__ import annotations

import sys

if __name__ == "__main__":
    sys.dont_write_bytecode = True

import argparse
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import re
import struct
import subprocess


ROOT = Path(__file__).resolve().parents[1]
BASELINE_PYTHON = (3, 12)
BASELINE_R5PY = "1.1.7"
BASELINE_JAVA = 21
JAVA_TIMEOUT_SECONDS = 10
DISTRIBUTIONS = ("r5py", "jpype1", "geopandas", "pandas", "numpy", "shapely", "pyproj", "rasterio")
CHECK_COMMAND = (
    "conda run --no-capture-output -n homereach-routing "
    "python scripts/check_routing_runtime.py"
)


def java_major_version(output: str) -> int | None:
    """Recognise Java/OpenJDK version lines, including the legacy 1.8 form."""
    match = re.search(
        r'^(?:openjdk|java)(?: version)?\s+"?(\d+)(?:\.(\d+))?(?=[.\s"+_-]|$)',
        output, re.MULTILINE,
    )
    if match is None:
        return None
    major = int(match.group(1))
    return int(match.group(2)) if major == 1 and match.group(2) else major


def find_java() -> Path | None:
    """Use a fixed executable name on absolute PATH entries, excluding the checkout."""
    executable_name = "java.exe" if os.name == "nt" else "java"
    current_directory = Path.cwd().resolve()
    for entry in os.get_exec_path():
        directory = Path(entry.strip('"'))
        if not entry or not directory.is_absolute():
            continue
        try:
            directory = directory.resolve()
            if directory == current_directory or directory.is_relative_to(ROOT):
                continue
            executable = (directory / executable_name).resolve()
            if executable.parent == current_directory or executable.is_relative_to(ROOT):
                continue
            if executable.is_file() and os.access(executable, os.X_OK):
                return executable
        except OSError:
            continue
    return None


def inspect_java() -> dict:
    executable = find_java()
    result = {"executable": str(executable) if executable else None,
              "major_version": None, "version_output": "", "status": "missing"}
    if executable is None:
        return result
    # These variables can inject agents/options even into `java -version`.
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() not in {"JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "_JAVA_OPTIONS"}}
    try:
        completed = subprocess.run(
            [str(executable), "-version"], shell=False, capture_output=True, stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", check=False,
            timeout=JAVA_TIMEOUT_SECONDS, env=environment,
        )
    except subprocess.TimeoutExpired:
        result.update(status="timeout", error=f"java -version exceeded {JAVA_TIMEOUT_SECONDS} seconds.")
        return result
    except OSError as error:
        result.update(status="execution_error", error=str(error))
        return result
    output = "\n".join(part.strip() for part in (completed.stderr, completed.stdout) if part.strip())
    result["version_output"] = output[:4000]
    if completed.returncode:
        result.update(status="execution_error", error=f"java -version exited with code {completed.returncode}.")
    else:
        result["major_version"] = java_major_version(output)
        result["status"] = "version_detected" if result["major_version"] is not None else "unreadable_version"
    return result


def inspect_runtime() -> dict:
    """Check the selected project baseline; installed metadata is not an import test."""
    blockers = []
    packages = {}
    for name in DISTRIBUTIONS:
        try:
            version = metadata.version(name)
            if not version or not version.strip():
                raise ValueError("empty version metadata")
            packages[name] = {"version": version, "status": "installed"}
        except metadata.PackageNotFoundError:
            packages[name] = {"version": None, "status": "missing"}
            blockers.append(f"Missing Python package: {name}.")
        except (OSError, ValueError) as error:
            packages[name] = {"version": None, "status": "unreadable_metadata"}
            blockers.append(f"Cannot read {name} package metadata: {error}.")
    bits = struct.calcsize("P") * 8
    if sys.version_info[:2] != BASELINE_PYTHON:
        blockers.append("The selected project baseline is Python 3.12; this interpreter has not been checked against it.")
    if bits != 64:
        blockers.append("The selected routing environment requires a 64-bit Python interpreter.")
    r5py_version = packages["r5py"]["version"]
    if r5py_version is not None and r5py_version != BASELINE_R5PY:
        blockers.append(f"The selected r5py baseline is {BASELINE_R5PY}; installed {r5py_version} needs a separate review.")
    prefix = Path(sys.prefix).resolve()
    conda_prefix = os.environ.get("CONDA_PREFIX")
    if conda_prefix and Path(conda_prefix).resolve() != prefix:
        blockers.append("CONDA_PREFIX and this Python interpreter disagree; use the explicit conda run command below.")
    java = inspect_java()
    if java["status"] != "version_detected":
        blockers.append(f"Java version check: {java['status']}. Use the homereach-routing environment with OpenJDK 21.")
    elif java["major_version"] != BASELINE_JAVA:
        blockers.append(f"The selected Java baseline is 21; detected {java['major_version']} needs a separate review.")
    return {
        "schema_version": 1,
        "status": "prerequisites_passed" if not blockers else "blocked",
        "python": {"executable": sys.executable, "version": platform.python_version(),
                   "bits": bits, "platform": platform.platform(), "prefix": str(prefix),
                   "conda_prefix": conda_prefix, "conda_environment": os.environ.get("CONDA_DEFAULT_ENV")},
        "packages": packages,
        "java": java,
        "blockers": blockers,
        "next_check_command": CHECK_COMMAND,
        "not_tested": ["Python package imports and native dependencies", "Embedded JVM and R5 JAR compatibility",
                       "Street/GTFS network loading", "Walking/transit routing and journey timing"],
        "routing_engine_imported": False,
        "embedded_jvm_started": False,
        "project_datasets_read": 0,
        "project_files_written": 0,
        "journeys_computed": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print a machine-readable inventory.")
    args = parser.parse_args(argv)
    report = inspect_runtime()
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
    else:
        print("ROUTING RUNTIME PREREQUISITES:", "PASSED" if not report["blockers"] else "BLOCKED")
        python = report["python"]
        print(f"Python: {python['version']} | {python['bits']}-bit | {python['executable']}")
        print("Environment:", python["conda_environment"] or "not reported", "|", python["prefix"])
        for name, package in report["packages"].items():
            print(f"Package {name}: {package['version'] or package['status']}")
        print("Java:", report["java"]["status"], "|", report["java"]["executable"] or "not found")
        if report["java"]["version_output"]:
            print(report["java"]["version_output"])
        if report["java"].get("error"):
            print("Java detail:", report["java"]["error"])
        for blocker in report["blockers"]:
            print("Blocked:", blocker)
        if report["blockers"]:
            print("Create the separate environment if absent: conda env create -f environment-routing.yml")
            print("Check that environment:", CHECK_COMMAND)
        else:
            print("Ready for a controlled engine smoke test; the routing engine has not been tested.")
        for item in report["not_tested"]:
            print("Not tested:", item)
        print("Project datasets read: 0 | Project files written: 0 | Journeys computed: 0")
    return 2 if report["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
