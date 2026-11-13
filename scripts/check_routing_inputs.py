"""Inspect the fixed commute-pilot inputs without building a routing network."""
from __future__ import annotations

import argparse
from importlib.util import find_spec
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true", help="Print a machine-readable report.")
    args = parser.parse_args()
    try:
        # pandas wraps missing NumPy in ImportError; check both names first.
        for dependency in ("numpy", "pandas"):
            if find_spec(dependency) is None:
                raise ModuleNotFoundError(f"No module named '{dependency}'", name=dependency)
        from homereach.routing import check_routing_inputs
    except ModuleNotFoundError as error:
        # A missing project module is a code/checkout error, not an environment hint.
        if not error.name or error.name.split(".")[0] == "homereach":
            raise
        message = f"Missing Python dependency: {error.name}"
        hint = ("From the project folder, run: conda run --no-capture-output "
                "-n homereach python scripts/check_routing_inputs.py")
        if args.json:
            print(json.dumps({"status": "environment_error", "error": message,
                              "python_executable": sys.executable, "hint": hint}))
        else:
            print(f"ROUTING INPUT PREFLIGHT ENVIRONMENT ERROR: {message}", file=sys.stderr)
            print(f"Python executable: {sys.executable}", file=sys.stderr)
            print(hint, file=sys.stderr)
        return 1
    try:
        report = check_routing_inputs(args.project_root)
    except (OSError, ValueError) as error:
        if args.json:
            print(json.dumps({"status": "invalid", "error": str(error)}, ensure_ascii=False))
        else:
            print(f"ROUTING INPUT PREFLIGHT INVALID: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
    else:
        print("ROUTING INPUT PREFLIGHT: BLOCKED")
        print(f"Service date: {report['service_date']} | Timezone: {report['timezone']}")
        print("GTFS archive/small-table checks:", report["gtfs"]["status"])
        for feed in report["gtfs"]["feeds"]:
            print(f"Feed {feed['feed_id']}: {feed['active_trip_records']} active trips; "
                  f"{feed['labelled_replacement_trip_records']} labelled replacements.")
        for check in report["checks"]:
            print("Checked:", check)
        for blocker in report["blockers"]:
            print("Blocked:", blocker)
        for boundary in report["not_validated"]:
            print("Not validated:", boundary)
        print("Project files written: 0 | Journeys computed: 0")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
