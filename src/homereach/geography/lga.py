"""Refactor of notebook 04: reviewed names -> ABS codes -> unchanged shapes.

No downloads, fuzzy matches, geometry repair, historical boundary assumptions,
model training or Streamlit edits. The source notebook is retained as evidence.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import geopandas as gpd
import pyogrio
import numpy as np
import pandas as pd
from shapely.geometry import shape

from homereach.io.dffh_rent import (
    AGGREGATE_LABELS, COLUMN_ORDER, KEY_COLUMNS, fingerprint,
    load_snapshot, read_panel_csv, require,
)

CODE = "lga_code_2025"
NAME = "abs_lga_name"
ALIAS_COLUMNS = ["rental_area_name", CODE, NAME, "match_note"]
CROSSWALK_COLUMNS = ["rental_area_name", "source_region", CODE, NAME,
                     "boundary_year", "match_method", "match_note"]
NATIVE_FIELDS = {"LGA_CODE25": CODE, "LGA_NAME25": NAME, "STE_CODE21": "state_code",
                 "STE_NAME21": "state_name", "AREASQKM": "abs_area_sqkm"}
GEOJSON_REL = Path("data/interim/geography/rent_map_2025q3.geojson")
GPKG_REL = Path("data/processed/geography/metro_lga_2025.gpkg")
GEO_DIR = Path("data/interim/geography")


def load_geo_snapshot(path: str | Path) -> dict[str, Any]:
    """Read the reviewed release contract; never guess a missing setting."""
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    needed = {"filename", "sha256", "layer", "boundary_year", "native_epsg",
              "web_epsg", "state_code", "state_name", "national_records",
              "national_null_geometry", "state_records", "council_records",
              "excluded_codes", "nonspatial_codes", "map_quarter", "mapped_records",
              "exact_matches", "alias_matches", "archive_extensions", "source_columns",
              "boundary_source", "publisher_page", "download_url", "scope_note"}
    require(isinstance(spec, dict) and needed.issubset(spec), "Incomplete LGA snapshot configuration.")
    require(Path(spec["filename"]).name == spec["filename"], "Boundary filename must not contain a path.")
    require(re.fullmatch(r"[0-9a-f]{64}", spec["sha256"]) is not None, "Invalid boundary SHA-256.")
    require(spec["boundary_year"] == 2025 and spec["map_quarter"] == "2025Q3",
            "This implementation is reviewed for 2025 boundaries and 2025Q3 rents only.")
    require(spec["native_epsg"] == 7844 and spec["web_epsg"] == 4326, "Unexpected reviewed CRS settings.")
    require(spec["state_code"] == "2" and spec["state_name"] == "Victoria", "Expected Victoria scope.")
    return spec


def load_aliases(path: str | Path) -> pd.DataFrame:
    """Read the editable review table as text; codes are identifiers."""
    frame = pd.read_csv(path, dtype="string", keep_default_na=False)
    require(frame.columns.tolist() == ALIAS_COLUMNS, "Unexpected alias-table columns.")
    require(frame.notna().all().all() and all(bool(str(v).strip()) for v in frame.to_numpy().ravel()),
            "Alias fields must be non-empty.")
    require(frame["rental_area_name"].is_unique, "Duplicate reviewed alias.")
    require(frame[CODE].str.fullmatch(r"2[0-9]{4}").all(), "Invalid Victorian alias code.")
    return frame


def select_latest(panel: pd.DataFrame, rent_spec: dict, geo_spec: dict) -> pd.DataFrame:
    """Validate the panel without re-reading Excel; select one quarter only."""
    require(panel.columns.tolist() == COLUMN_ORDER, "Unexpected rental schema.")
    require(panel[KEY_COLUMNS].notna().all().all() and not panel.duplicated(KEY_COLUMNS).any(),
            "Missing or duplicate rental analytical key.")
    require(not panel["rental_area_name"].isin(AGGREGATE_LABELS).any(), "Aggregate in rental panel.")
    for column, expected in {
        "area_type": "LGA", "property_type": rent_spec["property_type"],
        "source_file": rent_spec["filename"], "source_sheet": rent_spec["sheet"],
        "source_reporting_quarter": rent_spec["reporting_quarter"],
    }.items():
        require(panel[column].notna().all() and panel[column].eq(expected).all(), f"Unexpected {column}.")
    quarters = pd.period_range(rent_spec["first_quarter"], rent_spec["last_quarter"], freq="Q")
    n_areas = sum(rent_spec["metro_group_counts"].values())
    require(n_areas == geo_spec["mapped_records"] and len(panel) == n_areas * len(quarters),
            "Reviewed rental coverage changed.")
    # pandas 2/3 may use different datetime resolutions. Compare common units.
    dates = pd.DatetimeIndex(panel["quarter_end"]).as_unit("ns")
    expected = pd.PeriodIndex(panel["quarter"], freq="Q").to_timestamp(how="end").normalize().as_unit("ns")
    require(np.array_equal(dates.asi8, expected.asi8), "Quarter labels and end dates disagree.")
    for _, group in panel.groupby(["rental_area_name", "property_type"], sort=False):
        require(group.sort_values("quarter_end")["quarter"].tolist() == quarters.astype(str).tolist(),
                "Incomplete quarterly rental sequence.")
    for column in ["published_count", "median_weekly_rent"]:
        values = panel[column].to_numpy(dtype=float)
        require(np.isfinite(values).all() and (values > 0).all(), f"Invalid {column}.")
    require(pd.api.types.is_integer_dtype(panel["published_count"]), "Counts must retain integer dtype.")
    require(rent_spec["last_quarter"] == geo_spec["map_quarter"], "Unexpected map reporting quarter.")
    latest = panel.loc[panel["quarter"].eq(geo_spec["map_quarter"])].copy().reset_index(drop=True)
    require(len(latest) == n_areas and latest["rental_area_name"].is_unique, "Invalid latest-quarter inventory.")
    require(latest.groupby("source_region").size().to_dict() == rent_spec["metro_group_counts"],
            "Rental source-group composition changed.")
    return latest


def read_inputs(root: Path, geo_spec: dict) -> tuple[pd.DataFrame, dict, dict[Path, str]]:
    """Verify the rental fingerprint and track upstream files for later checks."""
    root = Path(root)
    input_path = root / "data/processed/rent_quarterly.csv"
    rent_spec_path = root / "config/rent_snapshot.json"
    quality_path = root / "data/processed/rent_quality_report.json"
    rent_spec = load_snapshot(rent_spec_path)
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    require(quality.get("source", {}).get("sha256") == rent_spec["sha256"], "Rental quality snapshot differs.")
    require(quality.get("output_sha256", {}).get(input_path.name) == fingerprint(input_path),
            "Rental CSV differs from its pipeline report. Recheck it; do not bypass this check.")
    latest = select_latest(read_panel_csv(input_path), rent_spec, geo_spec)
    paths = [input_path, rent_spec_path, quality_path, root / "config/lga_snapshot.json",
             root / "config/lga_name_aliases_2025.csv", root / "data/raw/geography" / geo_spec["filename"]]
    raw = root / "data/raw/rent" / rent_spec["filename"]
    if raw.is_file():
        require(fingerprint(raw) == rent_spec["sha256"], "Raw rental workbook differs from audit.")
        paths.append(raw)
    for rel in ["data/processed/rent_quarterly.parquet", "docs/lga_geography_audit.md",
                "notebooks/04_lga_geography_and_rent_map.ipynb",
                "data/interim/geography/rent_map_2025q3.html", "data/interim/geography/geography_manifest.json"]:
        if (root / rel).is_file():
            paths.append(root / rel)
    return latest, rent_spec, {p: fingerprint(p) for p in paths}


def verify_fingerprints(hashes: dict[Path, str]) -> None:
    for path, expected in hashes.items():
        require(path.is_file() and fingerprint(path) == expected, f"An upstream input changed: {path}")


def audit_boundaries(australia: gpd.GeoDataFrame, spec: dict) -> tuple[gpd.GeoDataFrame, pd.DataFrame, pd.DataFrame]:
    """Select Victorian councils; record special categories instead of inventing shapes."""
    require(australia.columns.tolist() == spec["source_columns"], "Boundary columns changed.")
    require(australia.crs is not None and australia.crs.to_epsg() == spec["native_epsg"], "Boundary CRS changed.")
    require(len(australia) == spec["national_records"] and int(australia.geometry.isna().sum()) == spec["national_null_geometry"],
            "National boundary inventory changed.")
    australia = australia.copy()
    for column in ["LGA_CODE25", "LGA_NAME25", "STE_CODE21", "STE_NAME21"]:
        australia[column] = australia[column].astype("string")
        require(australia[column].notna().all(), f"Missing boundary identifier: {column}.")
    require(australia["LGA_CODE25"].is_unique, "Duplicate national boundary code.")
    vic = australia.loc[australia["STE_CODE21"].eq(spec["state_code"])].copy()
    require(len(vic) == spec["state_records"] and vic["STE_NAME21"].eq(spec["state_name"]).all(),
            "State boundary inventory changed.")
    require(set(vic.loc[vic.geometry.isna(), "LGA_CODE25"]) == set(spec["nonspatial_codes"]),
            "Unexpected null geometry category.")
    excluded = vic.loc[vic["LGA_CODE25"].isin(spec["excluded_codes"])].copy()
    require(set(excluded["LGA_CODE25"]) == set(spec["excluded_codes"]), "Expected excluded codes changed.")
    excluded["exclusion_reason"] = excluded["LGA_CODE25"].map(spec["excluded_codes"])
    councils = vic.loc[~vic["LGA_CODE25"].isin(spec["excluded_codes"])].copy()
    require(len(councils) == spec["council_records"], "Council-area count changed.")
    validate_geometry(councils)
    require(councils["LGA_CODE25"].is_unique and councils["LGA_NAME25"].is_unique, "Ambiguous council lookup.")
    audit = pd.DataFrame([
        {"scope": name, "records": len(frame), "null_geometry": int(frame.geometry.isna().sum()),
         "empty_geometry": int(frame.geometry.is_empty.sum()),
         "invalid_non_null_geometry": int((frame.geometry.notna() & ~frame.geometry.is_valid).sum())}
        for name, frame in [("Australia (all codes)", australia), ("Victoria (all codes)", vic),
                            ("Victoria (council areas only)", councils)]
    ])
    return councils, audit, pd.DataFrame(excluded[["LGA_CODE25", "LGA_NAME25", "exclusion_reason"]])


def read_boundaries(path: Path, spec: dict) -> tuple[gpd.GeoDataFrame, pd.DataFrame, pd.DataFrame]:
    """Read the actual local ZIP without extraction or network requests."""
    path = Path(path)
    require(fingerprint(path) == spec["sha256"], "Boundary ZIP fingerprint changed. Re-audit; do not replace the expected hash.")
    with ZipFile(path) as archive:
        wanted = {spec["layer"] + suffix for suffix in spec["archive_extensions"]}
        require(set(archive.namelist()) == wanted and len(archive.namelist()) == len(wanted), "ZIP member inventory changed.")
        require(archive.testzip() is None, "Boundary archive CRC check failed.")
        metadata = ET.fromstring(archive.read(spec["layer"] + ".xml"))
        require(any("Creative Commons" in (node.text or "") for node in metadata.iter()), "Missing boundary licence metadata.")
    uri = f"/vsizip/{path.resolve().as_posix()}/{spec['layer']}.shp"
    frame = gpd.read_file(uri, engine="pyogrio")
    require(fingerprint(path) == spec["sha256"], "Boundary ZIP changed while being read.")
    return audit_boundaries(frame, spec)


def validate_geometry(frame: gpd.GeoDataFrame) -> None:
    require(isinstance(frame, gpd.GeoDataFrame) and frame.crs is not None, "Missing geometry/CRS.")
    require(not frame.geometry.is_empty.any() and not frame.geometry.isna().any(), "Missing or empty geometry.")
    require(frame.geometry.is_valid.all(), "Invalid geometry; investigate rather than automatically repair.")
    require(frame.geom_type.isin(["Polygon", "MultiPolygon"]).all(), "Non-polygon geometry.")


def build_crosswalk(source: pd.DataFrame, lookup: pd.DataFrame, aliases: pd.DataFrame) -> pd.DataFrame:
    """Exact names first; precisely cover remaining names with reviewed aliases."""
    for frame, fields, label in [(source, ["rental_area_name", "source_region"], "source"),
                                  (lookup, [CODE, NAME], "lookup"), (aliases, ALIAS_COLUMNS, "aliases")]:
        require(set(fields).issubset(frame.columns), f"Missing {label} fields.")
        require(frame[fields].notna().all().all(), f"Null {label} identifier.")
        require(all(bool(str(v).strip()) for v in frame[fields].to_numpy().ravel()), f"Blank {label} field.")
    require(source["rental_area_name"].is_unique, "Duplicate source name.")
    require(lookup[CODE].is_unique and lookup[NAME].is_unique, "Ambiguous boundary lookup.")
    require(aliases["rental_area_name"].is_unique, "Duplicate reviewed alias.")
    unmatched = set(source["rental_area_name"]) - set(lookup[NAME])
    require(set(aliases["rental_area_name"]) == unmatched, "Alias table must cover exactly the unmatched names; review unknown or unused aliases.")
    by_name, by_code = lookup.set_index(NAME)[CODE].to_dict(), lookup.set_index(CODE)[NAME].to_dict()
    by_alias = aliases.set_index("rental_area_name").to_dict(orient="index")
    rows = []
    for row in source.itertuples(index=False):
        name = row.rental_area_name
        if name in by_name:
            code, official, method, note = by_name[name], name, "exact_name", "Exact name within Victoria."
        else:
            alias = by_alias[name]
            code, official = alias[CODE], alias[NAME]
            require(by_code.get(code) == official, f"Reviewed code/name pair is invalid: {name}")
            method, note = "reviewed_alias", alias["match_note"]
        rows.append({"rental_area_name": name, "source_region": row.source_region,
                     CODE: code, NAME: official, "boundary_year": 2025,
                     "match_method": method, "match_note": note})
    result = pd.DataFrame(rows, columns=CROSSWALK_COLUMNS).sort_values("rental_area_name").reset_index(drop=True)
    for col in CROSSWALK_COLUMNS:
        if col != "boundary_year":
            result[col] = result[col].astype("string")
    require(result[CODE].str.fullmatch(r"2[0-9]{4}").all() and result[CODE].is_unique, "Missing, invalid or repeated mapped code.")
    return result


def join_boundaries(latest: pd.DataFrame, councils: gpd.GeoDataFrame, aliases: pd.DataFrame) -> tuple[gpd.GeoDataFrame, pd.DataFrame, gpd.GeoDataFrame]:
    """Attach the exact code's shape, keeping every original rental column."""
    lookup = councils[["LGA_CODE25", "LGA_NAME25"]].rename(columns=NATIVE_FIELDS)
    crosswalk = build_crosswalk(latest[["rental_area_name", "source_region"]], lookup, aliases)
    native = councils.loc[councils["LGA_CODE25"].isin(crosswalk[CODE]), list(NATIVE_FIELDS) + ["geometry"]].copy().rename(columns=NATIVE_FIELDS)
    native["boundary_year"] = 2025
    native["boundary_source"] = "Australian Bureau of Statistics; ASGS Edition 3 LGA 2025; CC BY 4.0"
    native = native.sort_values(CODE).reset_index(drop=True)
    validate_geometry(native)
    rents = latest.merge(crosswalk[["rental_area_name", CODE, "match_method", "match_note"]],
                         on="rental_area_name", how="left", validate="one_to_one")
    mapped = native.merge(rents, on=CODE, how="left", validate="one_to_one").sort_values("rental_area_name").reset_index(drop=True)
    verify_map(mapped, latest, crosswalk, native)
    return native, crosswalk, mapped


def verify_map(mapped: gpd.GeoDataFrame, rents: pd.DataFrame, crosswalk: pd.DataFrame, native: gpd.GeoDataFrame) -> None:
    validate_geometry(mapped)
    require(mapped.crs == native.crs, "Map lost its native CRS.")
    require(len(mapped) == len(rents) == len(crosswalk) == len(native), "Join lost or added records.")
    require(mapped[CODE].is_unique and mapped["rental_area_name"].is_unique, "Duplicate map feature.")
    fields = ["rental_area_name", "source_region", CODE, NAME, "boundary_year", "match_method", "match_note"]
    pd.testing.assert_frame_equal(mapped[fields].sort_values("rental_area_name").reset_index(drop=True).astype("string"),
                                  crosswalk[fields].sort_values("rental_area_name").reset_index(drop=True).astype("string"), check_exact=True)
    pd.testing.assert_frame_equal(pd.DataFrame(mapped[COLUMN_ORDER]).sort_values(KEY_COLUMNS).reset_index(drop=True),
                                  rents[COLUMN_ORDER].sort_values(KEY_COLUMNS).reset_index(drop=True), check_exact=True)
    by_code = native.set_index(CODE)
    require(set(mapped[CODE]) == set(by_code.index), "Geometry code set changed.")
    for row in mapped.itertuples(index=False):
        expected = by_code.loc[getattr(row, CODE)]
        require(row.geometry.equals_exact(expected.geometry, 0.0), "Mapped shape differs from its code's original shape.")
        for column in [NAME, "state_code", "state_name", "abs_area_sqkm", "boundary_year", "boundary_source"]:
            require(getattr(row, column) == expected[column], f"Boundary attribute changed: {column}.")


def to_web_geojson(mapped: gpd.GeoDataFrame) -> dict:
    web = mapped.to_crs(4326)
    validate_geometry(web)
    west, south, east, north = web.total_bounds
    require(144 < west < east < 147 and -39 < south < north < -37, "Implausible Melbourne map bounds.")
    export = web.copy()
    export["quarter_end"] = export["quarter_end"].dt.strftime("%Y-%m-%d")
    data = json.loads(export.to_json(drop_id=True, na="null"))
    for feature in data["features"]:
        feature["id"] = feature["properties"][CODE]
    return data


def check_native(actual: gpd.GeoDataFrame, expected: gpd.GeoDataFrame) -> None:
    """Compare codes, every attribute and native coordinates, not file bytes."""
    validate_geometry(actual)
    require(actual.crs == expected.crs and len(actual) == len(expected), "Native CRS/count changed.")
    require(set(actual.columns) == set(expected.columns) and actual[CODE].is_unique, "Native schema/codes changed.")
    actual, expected = actual.sort_values(CODE).reset_index(drop=True), expected.sort_values(CODE).reset_index(drop=True)
    for col in expected.columns:
        if col != "geometry":
            require(actual[col].tolist() == expected[col].tolist(), f"Native attribute changed: {col}.")
    require(all(a.equals_exact(b, 0.0) for a, b in zip(actual.geometry, expected.geometry)), "Native coordinates changed.")


def check_geojson(actual: dict, expected: dict) -> None:
    require(actual.get("type") == "FeatureCollection", "Invalid GeoJSON collection.")
    features = actual.get("features", [])
    require(len(features) == len(expected["features"]), "GeoJSON count changed.")
    by_id = {f.get("id"): f for f in features}
    require(len(by_id) == len(features), "Duplicate GeoJSON ID.")
    require(set(by_id) == {f["id"] for f in expected["features"]}, "GeoJSON IDs changed.")
    for item in expected["features"]:
        observed = by_id[item["id"]]
        require(observed.get("properties") == item["properties"], "GeoJSON attribute changed.")
        require(observed.get("geometry") is not None, "Missing GeoJSON geometry.")
        require(shape(observed["geometry"]).equals_exact(shape(item["geometry"]), 1e-10), "GeoJSON coordinates changed.")


def check_csv(path: Path, expected: pd.DataFrame) -> None:
    actual = pd.read_csv(path, dtype="string", keep_default_na=False)
    pd.testing.assert_frame_equal(actual, expected.astype("string").fillna("").reset_index(drop=True), check_exact=True)


def export_geography(root: Path, native: gpd.GeoDataFrame, crosswalk: pd.DataFrame,
                     mapped: gpd.GeoDataFrame, spec: dict, input_hashes: dict[Path, str],
                     *, source_rents: pd.DataFrame, check_only: bool = False) -> dict:
    """Compare earlier notebook outputs before any replacement; stage read-backs.

    HTML and notebook audit outputs are deliberately not rewritten. The build
    owns four data files and its own manifest. Re-run notebook 04 for its map UI.
    """
    verify_map(mapped, source_rents, crosswalk, native)
    data = to_web_geojson(mapped)
    tables = {"lga_crosswalk_2025.csv": crosswalk,
              "latest_rent_by_lga_code.csv": pd.DataFrame(mapped.drop(columns="geometry"))}
    previous = []
    if (root / GPKG_REL).exists():
        check_native(gpd.read_file(root / GPKG_REL, layer="metro_lga_2025", engine="pyogrio"), native)
        previous.append(GPKG_REL.name)
    if (root / GEOJSON_REL).exists():
        check_geojson(json.loads((root / GEOJSON_REL).read_text(encoding="utf-8")), data)
        previous.append(GEOJSON_REL.name)
    for name, table in tables.items():
        if (root / GEO_DIR / name).exists():
            check_csv(root / GEO_DIR / name, table)
            previous.append(name)
    verify_fingerprints(input_hashes)
    info = {"mapped_features": len(mapped), "exact_matches": int(crosswalk.match_method.eq("exact_name").sum()),
            "reviewed_aliases": int(crosswalk.match_method.eq("reviewed_alias").sum()),
            "unmatched": 0, "duplicate_codes": 0, "missing_or_invalid_geometry": 0,
            "previous_exports_compared": previous, "input_files_unchanged": True,
            "rental_fields_preserved": len(COLUMN_ORDER), "native_crs": "EPSG:7844", "web_crs": "EPSG:4326"}
    if check_only:
        return {**info, "check_only": True, "files_written": 0}
    (root / GEO_DIR).mkdir(parents=True, exist_ok=True)
    (root / GPKG_REL).parent.mkdir(parents=True, exist_ok=True)
    # All outputs are staged on the same drive as the project, important on Windows.
    with TemporaryDirectory(prefix="geo-build-", dir=root / GEO_DIR) as folder:
        stage = Path(folder)
        gpkg = stage / GPKG_REL.name
        pyogrio.write_dataframe(native, gpkg, driver="GPKG", layer="metro_lga_2025",
                                geometry_type="Unknown", promote_to_multi=False)
        check_native(gpd.read_file(gpkg, layer="metro_lga_2025", engine="pyogrio"), native)
        geojson = stage / GEOJSON_REL.name
        geojson.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        check_geojson(json.loads(geojson.read_text(encoding="utf-8")), data)
        web_back = gpd.read_file(geojson, engine="pyogrio").sort_values(CODE).reset_index(drop=True)
        web_expected = mapped.to_crs(4326).sort_values(CODE).reset_index(drop=True)
        require(web_back.crs.to_epsg() == 4326 and len(web_back) == len(mapped), "Spatial GeoJSON read-back failed.")
        require(web_back[CODE].astype(str).tolist() == web_expected[CODE].tolist(), "GeoJSON code read-back failed.")
        require(all(a.equals_exact(b, 1e-10) for a,b in zip(web_back.geometry,web_expected.geometry)), "Web geometry read-back failed.")
        outputs = [(gpkg, root / GPKG_REL), (geojson, root / GEOJSON_REL)]
        for name, table in tables.items():
            path = stage / name
            table.to_csv(path, index=False)
            check_csv(path, table)
            outputs.append((path, root / GEO_DIR / name))
        verify_fingerprints(input_hashes)
        manifest = {"created_at_utc": datetime.now(timezone.utc).isoformat(),
                    "builder": "scripts/build_lga_geography.py", "check_only": False,
                    "boundary_snapshot": spec, "quality": info,
                    "gpkg_readback_matches": True, "geojson_readback_matches": True,
                    "csv_readback_matches": True,
                    "html_action": "unchanged; use notebook 04 to render/export HTML",
                    "input_sha256": {str(p.relative_to(root)): v for p,v in input_hashes.items()},
                    "output_sha256": {str(dst.relative_to(root)): fingerprint(src) for src,dst in outputs},
                    "versions": {"pandas": pd.__version__, "geopandas": gpd.__version__}}
        manifest_file = stage / "geography_pipeline_report.json"
        manifest_file.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        # Per-file atomic replacement, not a multi-file database transaction.
        # Do not run simultaneous writers or leave derived files open in Excel/GIS.
        for src, dst in outputs:
            src.replace(dst)
        manifest_file.replace(root / GEO_DIR / manifest_file.name)
    verify_fingerprints(input_hashes)
    return manifest


def registry_update_text(path: Path, spec: dict) -> str:
    """Update boundaries only. Preserve custom notes/other rows; invent no dates."""
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields, rows = list(reader.fieldnames or []), list(reader)
    require({"dataset_id", "status"}.issubset(fields) and len(fields) == len(set(fields)), "Invalid registry header.")
    require(all(None not in r and all(v is not None for v in r.values()) for r in rows), "Malformed registry row.")
    matches = [r for r in rows if r["dataset_id"] == "boundaries"]
    require(len(matches) == 1, "Registry must contain exactly one boundaries row.")
    changes = {"status": "matched_validated", "official_page": spec["publisher_page"],
               "expected_format": "Shapefile (ZIP)", "source_filename": spec["filename"],
               "source_sha256": spec["sha256"], "source_layer": spec["layer"],
               "boundary_vintage": "2025", "native_crs": "EPSG:7844", "web_crs": "EPSG:4326",
               "map_reporting_quarter": "2025Q3", "processed_scope": "31 source-group metropolitan LGAs; 2025Q3 map only",
               "processed_file": GPKG_REL.as_posix(),
               "build_command": "python scripts/build_lga_geography.py --update-registry",
               "boundary_method_note": "ABS statistical boundaries, not legal definitions; reviewed rental name/code associations",
               "alias_configuration": "config/lga_name_aliases_2025.csv"}
    for col in changes:
        if col not in fields:
            fields.append(col)
    matches[0].update(changes)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader(); writer.writerows(rows)
    return stream.getvalue()


def save_registry(root: Path, text: str, before_hash: str) -> None:
    path = root / "docs/data_registry.csv"
    require(fingerprint(path) == before_hash, "Registry changed while build ran; preserve edits and rerun.")
    data = path.read_bytes()
    if data == text.encode("utf-8"):
        return
    backup = root / "data/interim/registry_backups" / f"data_registry_{before_hash}.csv"
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        backup.write_bytes(data)
    with TemporaryDirectory(prefix="registry-", dir=root / "docs") as folder:
        staged = Path(folder) / "data_registry.csv"
        staged.write_text(text, encoding="utf-8", newline="")
        staged.replace(path)
