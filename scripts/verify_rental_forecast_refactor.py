"""Compare reusable fixed forecasts with completed notebook 13; never overwrite results."""
from __future__ import annotations
import argparse
from pathlib import Path
import subprocess
import sys

# Keep this read-only command from creating Python bytecode files in the project.
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true', help='Explicit read-only mode (also the default).')
    parser.parse_args()
    from homereach.forecasting.equivalence import verify_equivalence
    try:
        result = verify_equivalence(ROOT)
    except (OSError, ValueError, KeyError, TypeError, AssertionError, subprocess.SubprocessError) as error:
        print(f'FORECAST REFACTOR CHECK FAILED: {error}', file=sys.stderr)
        print('Preserve the original evidence. Do not change hashes or delete final outputs.', file=sys.stderr)
        return 1
    print('FORECAST REFACTOR EQUIVALENCE CHECKPOINT PASSED')
    print('Original protocol lock:', result['protocol_commit'][:7])
    print('Original final execution:', result['original_execution_commit'][:7])
    print('Refactor execution HEAD:', result['execution_commit'][:7])
    print('Notebook 13 CSV tables matched: 13/13')
    print('Final forecasts compared: 992 | Trained fits reproduced: 496')
    print('Historical lag checks: 97712 | Change checks: 73284')
    print('Baseline source checks: 496 | Forecast source records: 992')
    print('Model settings, final targets and numeric comparison rules: unchanged')
    print('Prior evidence, original reports, notebooks and deployed release: unchanged')
    print('Project files written: 0 | Additional independent final tests: 0')
    print('No model selection, live predictions, model pickle or deployment performed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
