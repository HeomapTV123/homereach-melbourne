"""Prepare a self-contained release from the verified LOCAL explorer data."""
from pathlib import Path
import argparse
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from homereach.explorer.release import package_release

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=ROOT)
    parser.add_argument('--check-only', action='store_true', help='Validate and compare without writing release files.')
    args = parser.parse_args()
    package_release(args.project_root, check_only=args.check_only)

if __name__ == '__main__':
    main()
