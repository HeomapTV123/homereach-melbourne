"""Read-only final-evaluation specification check. Never reads rental data or fits models.

Run once before committing, then with --require-committed after committing.
Only the standard library and the already-installed Git executable are needed.
This is an audit gate, not proof that nobody has previously viewed outcomes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

PROTOCOL_FILE = "config/rental_final_evaluation_protocol.json"
LOCK_FILES = (
    PROTOCOL_FILE,
    "docs/rental_final_evaluation_protocol.md",
    "scripts/verify_rental_final_protocol.py",
)
EXPECTED_PROTOCOL_SHA256 = "f0168e345aafba1a64b883bef1fe351185d7cf57575ce870f252301b484d1495"
EXPECTED_BRANCH = "feat/rental-forecast-baselines"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON value is not allowed: {value}")


def json_object(data: bytes, label: str) -> dict[str, Any]:
    try:
        obj = json.loads(
            data.decode("utf-8-sig"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"Invalid JSON in {label}: {error}") from error
    require(isinstance(obj, dict), f"Expected a JSON object in {label}.")
    return obj


def canonical_json_sha256(obj: dict[str, Any]) -> str:
    """Ignore indentation, key order and LF/CRLF, not JSON values or list order."""
    payload = json.dumps(
        obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def quarter_number(value: str) -> int:
    require(isinstance(value, str), "Quarter must be a string.")
    match = re.fullmatch(r"([0-9]{4})Q([1-4])", value)
    require(match is not None, f"Invalid calendar quarter: {value!r}")
    assert match is not None
    return int(match.group(1)) * 4 + int(match.group(2)) - 1


def git_bytes(root: Path, *args: str, optional: bool = False) -> bytes | None:
    """Use read-only Git commands; no index refresh, network call or shell."""
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, check=False, timeout=30,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    if result.returncode:
        if optional:
            return None
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"Git check failed ({' '.join(args)}): {detail}")
    return result.stdout


def text_bytes(data: bytes) -> str:
    return data.decode("utf-8-sig").replace("\r\n", "\n")


def same_content(relative: str, left: bytes, right: bytes) -> bool:
    if relative.endswith(".json"):
        return canonical_json_sha256(json_object(left, relative)) == canonical_json_sha256(
            json_object(right, relative)
        )
    return text_bytes(left) == text_bytes(right)


def verify_project(root: Path, *, require_committed: bool = False) -> dict[str, Any]:
    root = root.resolve()
    repository_root = git_bytes(root, "rev-parse", "--show-toplevel")
    assert repository_root is not None
    require(
        Path(repository_root.decode("utf-8").strip()).resolve() == root,
        "Run the checker from the HomeReach project, not an outer repository.",
    )
    branch_bytes = git_bytes(root, "symbolic-ref", "--quiet", "--short", "HEAD", optional=True)
    branch = branch_bytes.decode("utf-8").strip() if branch_bytes else "(detached HEAD)"
    require(branch == EXPECTED_BRANCH, f"Expected branch {EXPECTED_BRANCH}; found {branch}.")

    files: dict[str, bytes] = {}
    for relative in LOCK_FILES:
        path = root / relative
        require(path.is_file(), f"Missing {relative}; copy all three supplied files.")
        files[relative] = path.read_bytes()
    protocol = json_object(files[PROTOCOL_FILE], PROTOCOL_FILE)
    protocol_digest = canonical_json_sha256(protocol)
    require(
        protocol_digest == EXPECTED_PROTOCOL_SHA256,
        "Final protocol differs from this reviewed specification. Do not edit the expected hash "
        "to bypass a failed check; review the change before scoring anything.",
    )

    checked = 0
    for relative, pinned in protocol["pinned_development_protocols"].items():
        path = root / relative
        require(path.is_file(), f"Missing previous protocol: {relative}")
        current_bytes = path.read_bytes()
        current = json_object(current_bytes, relative)
        require(current["protocol_id"] == pinned["protocol_id"], f"Wrong protocol ID: {relative}")
        require(
            canonical_json_sha256(current) == pinned["canonical_json_sha256"],
            f"Earlier protocol changed: {relative}. Keep the original experiments intact.",
        )
        committed_bytes = git_bytes(root, "show", f"HEAD:{relative}", optional=True)
        require(committed_bytes is not None, f"Earlier protocol is not committed: {relative}")
        assert committed_bytes is not None
        require(same_content(relative, current_bytes, committed_bytes), f"Uncommitted protocol edits: {relative}")
        index_bytes = git_bytes(root, "show", f":{relative}", optional=True)
        require(index_bytes is not None, f"Earlier protocol is missing from the Git index: {relative}")
        assert index_bytes is not None
        require(same_content(relative, current_bytes, index_bytes), f"Different staged protocol: {relative}")
        checked += 1

    periods = protocol["periods"]
    expected_numbers = list(range(quarter_number(periods["final_start"]), quarter_number(periods["final_end"]) + 1))
    actual_numbers = [quarter_number(q) for q in periods["final_target_quarters"]]
    require(actual_numbers == expected_numbers, "Final quarters must be consecutive, unique and ordered.")
    n_areas = protocol["target"]["area_count"]
    n_targets = n_areas * len(expected_numbers)
    require(n_targets == periods["targets_per_method"] == 248, "Final target count disagrees.")
    require(n_targets * len(protocol["methods"]) == periods["comparison_rows_all_methods"] == 992,
            "Four-method comparison count disagrees.")
    rolling = protocol["rolling_evaluation"]
    first_count = expected_numbers[0] - quarter_number(rolling["supervised_training_start"])
    last_count = expected_numbers[-1] - quarter_number(rolling["supervised_training_start"])
    require((first_count, last_count) == (94, 101), "Expanding training-window sizes disagree.")

    pending: list[str] = []
    for relative, current_bytes in files.items():
        head_bytes = git_bytes(root, "show", f"HEAD:{relative}", optional=True)
        index_bytes = git_bytes(root, "show", f":{relative}", optional=True)
        if (head_bytes is None or index_bytes is None
                or not same_content(relative, current_bytes, head_bytes)
                or not same_content(relative, current_bytes, index_bytes)):
            pending.append(relative)
    if require_committed:
        require(not pending, "Protocol files are not fully recorded in HEAD and the index: "
                + ", ".join(pending) + ". Commit the reviewed three-file update first.")
    head = git_bytes(root, "rev-parse", "HEAD")
    assert head is not None
    lock_commit = None
    if not pending:
        value = git_bytes(root, "log", "-1", "--format=%H", "--", PROTOCOL_FILE)
        assert value is not None
        lock_commit = value.decode("ascii").strip()
        require(bool(lock_commit), "Could not identify the protocol-recording commit.")
    return {
        "protocol_sha256": protocol_digest, "branch": branch,
        "earlier_protocols_checked": checked, "recorded_in_head": not pending,
        "pending_files": pending, "protocol_commit": lock_commit,
        "head_commit": head.decode("ascii").strip(),
        "final_quarters": len(expected_numbers), "targets_per_method": n_targets,
        "planned_comparison_rows": periods["comparison_rows_all_methods"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-committed", action="store_true", help="Fail until the three protocol files are committed and unchanged.")
    args = parser.parse_args(argv)
    try:
        result = verify_project(Path(__file__).resolve().parents[1], require_committed=args.require_committed)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(f"FINAL PROTOCOL CHECK FAILED: {error}", file=sys.stderr)
        return 1

    print("FINAL EVALUATION PROTOCOL CHECK PASSED")
    print("Branch:", result["branch"])
    print("Final period: 2023Q4-2025Q3 | LGAs: 31 | Quarters: 8")
    print("Planned forecasts per method: 248 | Methods: 4 | Planned comparison rows: 992")
    print("Primary comparison: damped change Ridge versus last observation")
    print("Fixed alpha: 1.0 | Fixed damping: 0.5 | Primary metric: MAE")
    print("Earlier development protocols unchanged: 4/4")
    print("Protocol files recorded in HEAD:", result["recorded_in_head"])
    print("Protocol SHA-256 (canonical JSON):", result["protocol_sha256"])
    if result["protocol_commit"]:
        print("Protocol commit:", result["protocol_commit"])
        print("Current HEAD:", result["head_commit"])
    else:
        print("Next: commit and push the reviewed three-file update, then require the committed check.")
    print("Rental observations read: 0 | Models fitted: 0 | Final-period forecasts scored: 0")
    print("Project files written: 0 | Network requests: 0")
    print("This is a protocol check, not a forecast result or proof of unviewed outcomes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
