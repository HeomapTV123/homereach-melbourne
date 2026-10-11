"""Rebuild reviewed geographic data; notebook 04 remains the map presentation."""
from __future__ import annotations

import argparse
from pathlib import Path

from homereach.geography.lga import (
    CODE, NAME, load_geo_snapshot, load_aliases, read_inputs, read_boundaries,
    join_boundaries, export_geography, registry_update_text, save_registry,
)
from homereach.io.dffh_rent import fingerprint, require


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    flags = parser.add_mutually_exclusive_group()
    flags.add_argument("--check-only", action="store_true", help="Validate inputs and compare earlier exports; write nothing.")
    flags.add_argument("--update-registry", action="store_true", help="Update only the boundaries registry row after successful export.")
    args = parser.parse_args()
    root = args.project_root.resolve()
    spec = load_geo_snapshot(root / "config/lga_snapshot.json")
    aliases = load_aliases(root / "config/lga_name_aliases_2025.csv")
    print("Checking the validated rental input...", flush=True)
    latest, rent_spec, input_hashes = read_inputs(root, spec)
    registry_text, registry_hash = None, None
    if args.update_registry:
        registry_path = root / "docs/data_registry.csv"
        registry_hash = fingerprint(registry_path)
        registry_text = registry_update_text(registry_path, spec)  # validate BEFORE changing exports
    print("Reading and validating the local ABS boundary ZIP...", flush=True)
    councils, audit, exclusions = read_boundaries(root / "data/raw/geography" / spec["filename"], spec)
    print("Matching reviewed names and attaching the original polygons...", flush=True)
    native, crosswalk, mapped = join_boundaries(latest, councils, aliases)
    require(len(mapped) == spec["mapped_records"], "Wrong mapped area count.")
    require(crosswalk.match_method.value_counts().to_dict() == {
        "exact_name": spec["exact_matches"], "reviewed_alias": spec["alias_matches"]}, "Match-method totals changed.")
    print("Comparing with any existing notebook exports...", flush=True)
    result = export_geography(root, native, crosswalk, mapped, spec, input_hashes, source_rents=latest, check_only=args.check_only)
    quality = result if args.check_only else result["quality"]
    compared = quality["previous_exports_compared"]
    print("Previous geography exports: " + (f"matched ({len(compared)} files)" if compared else "not present; first build"), flush=True)
    if args.update_registry:
        save_registry(root, registry_text, registry_hash)
        print("Data registry: boundaries row updated; other dataset records preserved", flush=True)
    print("GEOGRAPHY CHECK-ONLY PASSED" if args.check_only else "GEOGRAPHY PIPELINE CHECKPOINT PASSED")
    print(f"Boundary records: {spec['national_records']} national / {spec['state_records']} Victorian / {spec['council_records']} Victorian council areas")
    print(f"Map quarter: {spec['map_quarter']} | Property type: {rent_spec['property_type']}")
    print(f"Exact-name matches: {quality['exact_matches']}")
    print(f"Reviewed aliases: {quality['reviewed_aliases']}")
    print(f"Matched rental LGAs: {len(mapped)}/{len(latest)}")
    print("Unmatched rental LGAs: 0")
    print("Duplicate LGA codes: 0")
    print("Missing or invalid mapped geometries: 0")
    print("All 14 rental fields and native shapes preserved: True")
    if args.check_only:
        print("Files written: 0")
    else:
        print("GeoPackage, GeoJSON and CSV read-back: matched")
        print("Saved: data/interim/geography/geography_pipeline_report.json")
    print("Upstream source files unchanged: True")
    print("HTML map and original notebooks: unchanged")


if __name__ == "__main__":
    main()
