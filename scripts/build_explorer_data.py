"""Prepare the real-data explorer from completed pipeline outputs (no GTFS rescan)."""
from pathlib import Path
import argparse
from homereach.explorer.bundle import run_build


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--check-only", action="store_true", help="Validate and compare; write nothing.")
    args = parser.parse_args()
    run_build(args.project_root, check_only=args.check_only)


if __name__ == "__main__":
    main()
