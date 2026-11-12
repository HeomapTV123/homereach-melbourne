"""Inspect the fixed commute-pilot inputs without building a routing network."""
from __future__ import annotations

import argparse
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
    from homereach.routing import check_routing_inputs
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
