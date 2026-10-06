"""Build HomeReach's audited 14-column rental table without a notebook kernel."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from homereach.io.dffh_rent import (
    build_panel, fingerprint, load_snapshot, read_workbook, require,
    updated_registry_text, validate_panel, write_outputs,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update-registry", action="store_true",
                        help="Update only the rent row of docs/data_registry.csv after a successful build.")
    parser.add_argument("--check-only", action="store_true",
                        help="Validate source and rebuilt in-memory table; do not write or compare export files.")
    args = parser.parse_args(argv)
    if args.check_only and args.update_registry:
        parser.error("Use --check-only alone; it must not modify the registry.")

    root = Path(__file__).resolve().parents[1]
    if not (root / "pyproject.toml").is_file():
        parser.error("Copy this file into the existing project's scripts folder.")
    try:
        spec = load_snapshot(root / "config" / "rent_snapshot.json")
        source = root / "data" / "raw" / "rent" / spec["filename"]
        registry = root / "docs" / "data_registry.csv"
        # Validate the existing registry early so a malformed file does not cause
        # a surprise only after data exports have been replaced.
        registry_text = updated_registry_text(registry, spec) if args.update_registry else None
        print("Reading audited workbook...")
        raw = read_workbook(source, spec)
        print("Building and validating the rental panel...")
        panel = build_panel(raw, spec)
        quality = validate_panel(panel, raw, spec)
        require(fingerprint(source) == spec["sha256"], "Original workbook changed.")
        if args.check_only:
            print("PIPELINE VALIDATION PASSED (no files written)")
        else:
            manifest = write_outputs(panel, raw, spec, root / "data" / "processed", source)
            compared = manifest["previous_exports_compared"]
            print("Previous exports: " + ("matched (" + ", ".join(compared) + ")" if compared else "not present; first build"))
            print("CSV and Parquet read-back: matched")
            if registry_text is not None:
                # Preserve the exact pre-update registry once, without replacing it on reruns.
                backup_dir = root / "data" / "interim" / "registry_backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                backup = backup_dir / f"data_registry_{fingerprint(registry)[:12]}.csv"
                if not backup.exists():
                    backup.write_bytes(registry.read_bytes())
                with TemporaryDirectory(prefix=".registry-staging-", dir=registry.parent) as temp:
                    staged = Path(temp) / "data_registry.csv"
                    staged.write_text(registry_text, encoding="utf-8")
                    staged.replace(registry)
                print("Data registry: rent row updated; other dataset records preserved")
            print("PIPELINE CHECKPOINT PASSED")
        print(f"Rows: {quality['rows']}")
        print(f"Columns: {quality['columns']}")
        print(f"Metro LGAs: {quality['lga_count']}")
        print(f"Quarters: {quality['quarter_count']} ({quality['first_quarter']} to {quality['last_quarter']})")
        print(f"Duplicate keys: {quality['duplicate_keys']}")
        print(f"Missing count values: {quality['missing_count_values']}")
        print(f"Missing rent values: {quality['missing_rent_values']}")
        print(f"Source numeric values verified: {quality['source_values_verified']}")
        print("Original workbook unchanged: True")
        return 0
    except (OSError, ValueError, ImportError) as error:
        print(f"BUILD STOPPED: {error}", file=sys.stderr)
        print("Keep the source unchanged and review the error; do not delete checks to bypass it.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
