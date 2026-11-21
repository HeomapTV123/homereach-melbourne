"""Audit the pinned local GTFS timetable without calculating journeys."""
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
    parser.add_argument("--work-root", type=Path,
                        help="Existing temporary directory outside the project (ZIP spool and SQLite index).")
    parser.add_argument("--json", action="store_true", help="Print the complete report as JSON to stdout.")
    args = parser.parse_args()
    try:
        for dependency in ("numpy", "pandas"):
            if find_spec(dependency) is None:
                raise ModuleNotFoundError(f"No module named '{dependency}'", name=dependency)
        from homereach.routing.timetable_audit import audit_routing_timetable
    except ModuleNotFoundError as error:
        if not error.name or error.name.split(".")[0] == "homereach":
            raise
        report = {"status": "environment_error", "error": f"Missing Python dependency: {error.name}",
                  "python_executable": sys.executable,
                  "hint": "Use conda run --no-capture-output -n homereach python scripts/audit_routing_timetable.py"}
        if args.json:
            print(json.dumps(report, ensure_ascii=False))
        else:
            print(f"GTFS TIMETABLE AUDIT: ENVIRONMENT ERROR: {report['error']}", file=sys.stderr)
            print(report["hint"], file=sys.stderr)
        return 1
    report = audit_routing_timetable(
        args.project_root, work_root=args.work_root,
        progress=lambda message: print(message, file=sys.stderr, flush=True),
    )
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
    else:
        print("GTFS TIMETABLE AUDIT:", report["status"].upper())
        if "service_date" in report:
            print(f"Service date: {report['service_date']} | Timezone: {report['timezone']}")
        for feed in report["feeds"]:
            print(f"Feed {feed['feed_id']}: {feed['rows_scanned']:,} source rows; "
                  f"{feed['active_rows_scanned']:,} active rows; {feed['status']}.")
            print(f"  Rows with times at/after 24:00:00: {feed['rows_with_extended_times']:,}; "
                  f"active: {feed['active_rows_with_extended_times']:,}.")
            for issue in feed["issues"]:
                print(f"  {issue['severity']}: {issue['code']}: {issue['count']:,}")
                for example in issue["examples"][:2]:
                    print("    ", json.dumps(example, ensure_ascii=False))
        for message in report["errors"]:
            print("Error:", message)
        for message in report["blockers"]:
            print("Blocked:", message)
        print("Full source scan completed:", report["scan_complete"])
        print("Protected inputs unchanged:", report["protected_inputs_unchanged"])
        print("Temporary workspace removed:", report["temporary_workspace_removed"])
        for boundary in report["not_validated"]:
            print("Not validated:", boundary)
        print("Project files written: 0 | Journeys computed: 0 | Routing ready: False")
    return {"passed": 0, "blocked": 2}.get(report["status"], 1)


if __name__ == "__main__":
    raise SystemExit(main())
