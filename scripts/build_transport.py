"""Rebuild the audited stop/LGA assignments and date-specific service indicators."""
from __future__ import annotations
import argparse
from pathlib import Path
from homereach.transport.pipeline import run_transport


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root',type=Path,default=Path(__file__).resolve().parents[1])
    flags=parser.add_mutually_exclusive_group()
    flags.add_argument('--check-only',action='store_true',help='Rebuild and compare; no project output or registry writes.')
    flags.add_argument('--update-registry',action='store_true',help='Update only the GTFS registry record after successful export.')
    parser.add_argument('--chunk-rows',type=int,default=100_000,help='CSV read chunk size; does not change results or cap all active-feed memory.')
    args=parser.parse_args()
    try:
        run_transport(args.project_root,check_only=args.check_only,update_registry=args.update_registry,chunk_rows=args.chunk_rows)
    except (OSError,ValueError,AssertionError,KeyError) as error:
        parser.exit(1,f'\nTransport build stopped: {error}\nKeep the sources and previous outputs. Do not change fingerprints to bypass the check.\n')


if __name__=='__main__':main()
