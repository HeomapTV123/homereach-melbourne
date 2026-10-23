"""Build and verify the explorer's local data bundle, without running notebooks.

Only data/processed/explorer is written. Source files, notebook evidence, registry,
synthetic demo and the existing pipelines remain untouched. No network requests.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
from shapely.geometry import shape

from .analysis import (AM_WINDOW, CATEGORY_LABELS, CODE, RENT_QUARTER, SERVICE_DATE,
                       TIMEZONE, derive_tables, fingerprint, load_inputs, read_json, require)

MANIFEST = "explorer_manifest.json"
GEOJSON = "lga_boundaries_2025.geojson"
TABLE_NAMES = (
    "am_lga_category_comparison.csv", "lga_transport_comparison.csv",
    "rent_transport_comparison.csv", "am_stop_denominator_comparison.csv",
    "study_area_reconciliation.csv", "source_periods.csv",
    "rental_history.csv", "lga_service_categories.csv",
)
REPORTS = (
    "data/processed/transport/transport_pipeline_report.json",
    "data/interim/geography/geography_pipeline_report.json",
    "data/processed/rent_quality_report.json",
)


@dataclass
class ExplorerBundle:
    tables: dict[str, pd.DataFrame]
    geometry: dict[str, Any]
    manifest: dict[str, Any]

    @property
    def areas(self) -> pd.DataFrame:
        return self.tables["rent_transport_comparison.csv"]


def table_schema(frame: pd.DataFrame) -> dict:
    return {"rows": len(frame), "columns": frame.columns.tolist(),
            "dtypes": {c: str(frame[c].dtype) for c in frame}}


def read_table(path: Path, schema: dict) -> pd.DataFrame:
    """Restore CSV types, including missing numeric ratios and nanosecond dates."""
    dates, types = [], {}
    for column in schema["columns"]:
        dtype = schema["dtypes"][column]
        if dtype.startswith("datetime64["):
            dates.append(column)
        elif dtype.startswith("string") or dtype in ("str", "object"):
            types[column] = "string"
        else:
            types[column] = dtype
    numeric_na = {c: [""] for c, d in types.items() if d in ("float64", "Float64", "Int64")}
    result = pd.read_csv(path, dtype=types, parse_dates=dates, keep_default_na=False,
                         na_values=numeric_na, float_precision="round_trip")
    for c in dates:
        result[c] = pd.DatetimeIndex(result[c]).as_unit("ns")
    require(result.columns.tolist() == schema["columns"] and len(result) == schema["rows"],
            f"Schema mismatch in {path.name}.")
    return result


def compare_csv(path: Path, expected: pd.DataFrame) -> None:
    try:
        actual = read_table(path, table_schema(expected))
        pd.testing.assert_frame_equal(actual, expected.reset_index(drop=True), check_dtype=False, check_exact=True)
    except (AssertionError, TypeError, ValueError, KeyError) as error:
        raise ValueError(f"Values differ in {path}. Retain the file and investigate; no force overwrite.") from error


def validate_geometry_payload(payload: dict, areas: pd.DataFrame) -> None:
    require(payload.get("type") == "FeatureCollection", "Expected a GeoJSON FeatureCollection.")
    features = payload.get("features", [])
    require(len(features) == len(areas), "Map feature count differs from the comparison table.")
    expected = areas.set_index(CODE).abs_lga_name.to_dict()
    ids = []
    for feature in features:
        props = feature.get("properties", {})
        code = props.get(CODE)
        require(isinstance(code, str) and code in expected, "Unknown or non-text map code.")
        require(feature.get("id") == code and props.get("abs_lga_name") == expected[code], "Map code/name differs.")
        geom = shape(feature.get("geometry"))
        require(geom.geom_type in ("Polygon", "MultiPolygon") and not geom.is_empty and geom.is_valid,
                "Invalid or missing area geometry.")
        minx, miny, maxx, maxy = geom.bounds
        require(-180 <= minx <= maxx <= 180 and -90 <= miny <= maxy <= 90, "Map is not in longitude/latitude.")
        ids.append(code)
    require(len(set(ids)) == len(ids) and set(ids) == set(expected), "Map codes are duplicated or incomplete.")


def create_geometry(path: Path, geo_spec: dict, areas: pd.DataFrame) -> dict:
    native = gpd.read_file(path, engine="pyogrio")
    require(native.crs is not None and native.crs.to_epsg() == geo_spec["native_epsg"], "Unexpected native CRS.")
    require(native[CODE].is_unique and len(native) == len(areas), "Native area inventory changed.")
    native[CODE] = native[CODE].astype("string")
    expected = areas.set_index(CODE).abs_lga_name.to_dict()
    require(native.set_index(CODE).abs_lga_name.to_dict() == expected, "Native code/name inventory changed.")
    network_before = pyproj.network.is_network_enabled()
    pyproj.network.set_network_enabled(False)
    try:
        web = native[[CODE, "abs_lga_name", "geometry"]].to_crs(epsg=4326)
    finally:
        pyproj.network.set_network_enabled(network_before)
    # No simplification, repair, snapping, raw-file edits or external map downloads.
    payload = json.loads(web.set_index(CODE, drop=False).sort_index().to_json(drop_id=False))
    validate_geometry_payload(payload, areas)
    return payload


def verify_unchanged(hashes: dict[Path, str]) -> None:
    for path, digest in hashes.items():
        require(path.is_file() and fingerprint(path) == digest, f"Input changed during build: {path}")


def validate_bundle_tables(tables: dict[str, pd.DataFrame]) -> None:
    require(set(tables) == set(TABLE_NAMES), "Incomplete explorer table inventory.")
    areas = tables["rent_transport_comparison.csv"]
    require(len(areas) == 31 and areas[CODE].is_unique, "Explorer needs exactly 31 unique LGA codes.")
    require(areas.quarter.eq(RENT_QUARTER).all() and areas.transport_service_date.eq(SERVICE_DATE).all(),
            "Explorer periods differ from the reviewed snapshots.")
    require(areas.property_type.eq("2 bedroom flats").all(), "Wrong property category.")
    history = tables["rental_history.csv"]
    require(len(history) == 3286 and set(history[CODE]) == set(areas[CODE]), "Rental history inventory changed.")
    require(not any(c.startswith("am_") or c.startswith("transport_") for c in history),
            "Historical rent must not be backfilled with newer transport features.")
    require(len(tables["lga_service_categories.csv"]) == 248, "Incomplete service category grid.")
    require(int(areas.am_departure_events.sum()) == 158932, "AM event total changed.")
    network = tables["study_area_reconciliation.csv"]
    am = network.loc[network.window.eq(AM_WINDOW)]
    require(len(am) == 1 and int(am.iloc[0].distinct_study_area_trips) == 5768,
            "Distinct study-area trips must not be computed by summing LGA counts.")


def run_build(root: Path, *, check_only: bool = False) -> dict:
    root = Path(root).resolve()
    print("Verifying processed rental, geography and transport inputs...", flush=True)
    inputs = load_inputs(root)
    print("Rebuilding the notebook 08 comparison and checking independent totals...", flush=True)
    tables = derive_tables(inputs)
    validate_bundle_tables(tables)
    geo = create_geometry(inputs["native_path"], inputs["geo_spec"], tables["rent_transport_comparison.csv"])
    hashes = dict(inputs["input_hashes"])

    # Notebook evidence is read-only; recheck its own manifest before comparing.
    eda = root / "data/interim/transport_rent_eda"
    eda_manifest_path = eda / "eda_manifest.json"
    existing_references = [name for name in TABLE_NAMES[:6] if (eda / name).is_file()]
    notebook_compared = []
    if existing_references:
        require(eda_manifest_path.is_file(), "Notebook 08 tables exist without their manifest; review the EDA export.")
        eda_manifest = read_json(eda_manifest_path)
        hashes[eda_manifest_path] = fingerprint(eda_manifest_path)
        for name in existing_references:
            path = eda / name
            digest = fingerprint(path)
            require(eda_manifest.get("output_sha256", {}).get(name) == digest,
                    f"Notebook reference changed since its manifest: {name}")
            compare_csv(path, tables[name])
            hashes[path] = digest
            notebook_compared.append(name)
    print(f"Notebook 08 tables matched: {len(notebook_compared)}/6", flush=True)
    if len(notebook_compared) != 6:
        print("Absent references were not compared. The builder does not execute notebooks.", flush=True)

    dest = root / "data/processed/explorer"
    prior = {p: fingerprint(p) for p in dest.rglob("*") if p.is_file()} if dest.exists() else {}
    compared = []
    for name, table in tables.items():
        if (dest / name).is_file():
            compare_csv(dest / name, table)
            compared.append(name)
    if (dest / GEOJSON).is_file():
        require(read_json(dest / GEOJSON) == geo, "Existing explorer geometry differs; investigate before replacing it.")
        compared.append(GEOJSON)
    print(f"Previous explorer data files matched: {len(compared)}/9", flush=True)
    manifest = {
        "schema_version": 1, "builder": "scripts/build_explorer_data.py", "check_only": check_only,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {"rental_quarter": RENT_QUARTER, "rental_history": ["1999Q2", RENT_QUARTER],
                  "property_type": "2 bedroom flats", "boundary_year": 2025, "lga_count": 31,
                  "transport_service_date": SERVICE_DATE, "timezone": TIMEZONE,
                  "morning_window": "07:00 inclusive to 09:00 exclusive", "selected_feeds": ["2", "3", "4"],
                  "category_labels": CATEGORY_LABELS, "eligibility": inputs["spec"]["eligibility"],
                  "score_or_prediction": False},
        "quality": {"joined_lgas": 31, "unmatched_lgas": 0, "duplicate_codes": 0,
                    "rental_history_rows": 3286, "service_category_rows": 248,
                    "am_events": 158932, "distinct_study_area_am_trips": 5768,
                    "rental_fields_preserved": 14, "input_files_unchanged": True,
                    "geometry_features": 31, "raw_gtfs_scans": 0},
        "input_sha256": {p.relative_to(root).as_posix(): h for p, h in hashes.items()},
        "upstream_report_sha256": {p: fingerprint(root / p) for p in REPORTS},
        "notebook_tables_compared": notebook_compared, "previous_exports_compared": compared,
        "versions": {"python": sys.version.split()[0], "pandas": pd.__version__, "geopandas": gpd.__version__},
    }
    verify_unchanged(hashes); verify_unchanged(prior)
    if not check_only:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".explorer-stage-", dir=dest.parent) as temp:
            stage = Path(temp)
            for name, table in tables.items():
                table.to_csv(stage / name, index=False, encoding="utf-8", date_format="%Y-%m-%d", lineterminator="\n")
                compare_csv(stage / name, table)
            (stage / GEOJSON).write_text(json.dumps(geo, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
            require(read_json(stage / GEOJSON) == geo, "GeoJSON round trip failed.")
            validate_geometry_payload(read_json(stage / GEOJSON), tables["rent_transport_comparison.csv"])
            manifest.update(output_schemas={n: table_schema(t) for n, t in tables.items()},
                            output_sha256={n: fingerprint(stage / n) for n in [*tables, GEOJSON]},
                            csv_readback_matches=True, geojson_readback_matches=True)
            (stage / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            require(read_json(stage / MANIFEST) == manifest, "Manifest round trip failed.")
            verify_unchanged(hashes); verify_unchanged(prior)
            dest.mkdir(parents=True, exist_ok=True)
            # Publish the manifest last. Per-file replacements are not a database transaction.
            for name in [*tables, GEOJSON, MANIFEST]:
                (stage / name).replace(dest / name)
        print("Eight CSV tables and the GeoJSON reloaded and matched.", flush=True)
    print("EXPLORER CHECK-ONLY PASSED" if check_only else "EXPLORER DATA CHECKPOINT PASSED")
    print("Comparison LGAs: 31 | Rental history rows: 3286 | Service-category rows: 248")
    print("Rent: 2025Q3 | Transport: 2026-10-13 | Boundaries: 2025")
    print("AM events: 158932 | Distinct study-area AM trips: 5768")
    print("Input files, notebooks, registry and synthetic demo: unchanged")
    print("Raw GTFS scans: 0")
    print("Project outputs written: 0" if check_only else "Saved: data/processed/explorer/explorer_manifest.json")
    return manifest


def bundle_signature(root: Path) -> str:
    """Cache key includes actual bundle bytes and upstream reports, not just filenames."""
    root = Path(root).resolve(); folder = root / "data/processed/explorer"
    manifest_path = folder / MANIFEST
    if not manifest_path.is_file():
        raise FileNotFoundError("Explorer data is not built. Run: python scripts/build_explorer_data.py")
    manifest = read_json(manifest_path)
    require(manifest.get("schema_version") == 1 and manifest.get("builder") == "scripts/build_explorer_data.py"
            and manifest.get("check_only") is False, "Invalid or incomplete explorer build manifest.")
    expected_names = set(TABLE_NAMES) | {GEOJSON}
    require(set(manifest.get("output_sha256", {})) == expected_names, "Incomplete explorer manifest.")
    require(set(manifest.get("output_schemas", {})) == set(TABLE_NAMES), "Incomplete explorer table schemas.")
    parts = [fingerprint(manifest_path)]
    for name in sorted(expected_names):
        path = folder / name
        require(path.is_file(), f"Explorer file missing: {name}. Rebuild the explorer data.")
        digest = fingerprint(path)
        require(digest == manifest["output_sha256"][name], f"Explorer file changed: {name}. Do not edit exported files.")
        parts.append(digest)
    for rel in REPORTS:
        p = root / rel
        require(p.is_file() and manifest.get("upstream_report_sha256", {}).get(rel) == fingerprint(p),
                "Upstream pipeline reports changed or are missing. Rebuild explorer data before viewing it.")
    require(manifest.get("csv_readback_matches") is True and manifest.get("geojson_readback_matches") is True,
            "Explorer read-back checks are incomplete.")
    return "|".join(parts)


def load_bundle(root: Path, expected_signature: str | None = None) -> ExplorerBundle:
    root = Path(root).resolve(); folder = root / "data/processed/explorer"
    signature = bundle_signature(root)
    require(expected_signature is None or expected_signature == signature, "Explorer files changed while opening the app.")
    manifest = read_json(folder / MANIFEST)
    tables = {n: read_table(folder / n, manifest["output_schemas"][n]) for n in TABLE_NAMES}
    validate_bundle_tables(tables)
    geometry = read_json(folder / GEOJSON)
    validate_geometry_payload(geometry, tables["rent_transport_comparison.csv"])
    require(bundle_signature(root) == signature, "Explorer bundle changed during reading.")
    return ExplorerBundle(tables, geometry, manifest)
