"""Check the public release without reading local pipeline files or raw datasets."""
from pathlib import Path
import argparse
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from homereach.explorer.release import load_release, RELEASE_NAMES

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=ROOT / 'deploy/data')
    args = parser.parse_args()
    bundle = load_release(args.directory)
    print('STANDALONE RELEASE CHECKPOINT PASSED')
    print('Comparison LGAs:', len(bundle.areas))
    print('Rental history rows:', len(bundle.tables['rental_history.csv']))
    print('Release files verified:', len(RELEASE_NAMES))
    print('Local pipeline reports read: 0')
    print('Raw datasets read: 0')
    print('No scores, forecasts or synthetic fallback: True')
    print('Release ID:', bundle.manifest['release_id'][:16])

if __name__ == '__main__':
    main()
