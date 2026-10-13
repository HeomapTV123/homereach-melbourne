"""Orchestrate a read-only check or staged export of the audited transport build.

Notebook reference artifacts remain unchanged. New reproducible outputs are
written under data/processed/transport/. No notebook is read or executed here.
"""
from __future__ import annotations

import csv
import io
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from zipfile import ZipFile

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import pyproj
import shapely

from homereach.geography.lga import (
    CROSSWALK_COLUMNS, load_geo_snapshot, load_aliases, build_crosswalk,
    read_boundaries,
)
from .gtfs import require, sha256_file, read_json, read_feed_tables, build_active_trips
from .spatial import build_spatial, CODE, NAME
from .service import (
    WINDOWS, CATEGORY_FEED, COUNT_FIELDS, categorize_trips,
    scan_service_feed, combine_service_results,
)

SOURCE_HASH = "c88af3abcaf0872e45196dcc1d5af9bc20a82c54a00a9dfef46c809ec2e34814"
SERVICE_DATE = "2026-10-13"
SPATIAL_NAMES = (
    "stop_lga_matches.csv", "location_selection_counts.csv", "excluded_location_records.csv",
    "spatial_candidates.csv", "spatial_match_summary.csv", "unassigned_stops.csv",
    "near_boundary_review.csv", "stop_records_by_lga_and_feed.csv",
)
SERVICE_NAMES = (
    "active_trip_lookup.csv", "trip_stop_scope.csv", "lga_service_indicators.csv",
    "stop_service_indicators.csv", "trip_lga_memberships.csv", "feed_service_summary.csv",
    "event_filter_audit.csv", "scan_summary.csv", "event_trace_examples.csv",
)
POINT_NAME = "stop_lga_matches.gpkg"
REPORT_NAME = "transport_pipeline_report.json"


def load_transport_snapshot(path: Path) -> dict[str, Any]:
    """Version 1 implements one audited date/snapshot, not an arbitrary feed API."""
    spec = read_json(path)
    pinned = {
        "schema_version": 1, "filename": "gtfs.zip", "sha256": SOURCE_HASH,
        "service_date": SERVICE_DATE, "timezone": "Australia/Melbourne",
        "feed_ids": ["2", "3", "4"], "point_epsg": 4326, "native_epsg": 7844,
        "match_epsg": 7855, "boundary_year": 2025, "near_boundary_metres": 10.0,
        "lga_count": 31, "replacement_label": "Replacement Bus",
        "rental_reporting_quarter": "2025Q3",
        "windows": {key: list(value) for key, value in WINDOWS.items()},
        "category_feed": CATEGORY_FEED,
        "location_counts": {"2": 2859, "3": 1623, "4": 22633},
        "platform_counts": {"2": 775, "3": 1623, "4": 22633},
        "active_trip_counts": {"2": 2828, "3": 5044, "4": 27708},
        "replacement_trip_counts": {"2": 52, "3": 0, "4": 0},
        "scan_rows": {"2": 688380, "3": 2568892, "4": 8589911},
        "spatial_counts": {"matched_within": 21426, "outside_selected_lgas": 3605},
        "near_boundary_count": 443,
        "expected_totals": {"source_rows":11847183,"active_trips":35580,"active_events":1311746,
                            "service_day_events":1175281,"am_events":158932,"am_trips":5768,"lga_rows":248},
        "outer_members": [f"{f}/google_transit.zip" for f in ("1","2","3","4","5","6","10","11")],
    }
    for key, expected in pinned.items():
        require(spec.get(key) == expected,
                f"Transport contract changed at {key}. Re-audit a new snapshot/method; do not bypass this check.")
    require(set(spec.get("feed_labels", {})) == set(spec["feed_ids"]), "Missing operational feed labels.")
    require(isinstance(spec.get("publisher_page"), str), "Missing publisher page.")
    return spec


def unchanged(hashes: dict[Path, str]) -> None:
    for path, expected in hashes.items():
        require(path.is_file() and sha256_file(path) == expected,
                f"Input/reference changed during build: {path}. No force-overwrite is supported.")


def read_inputs(root: Path, spec: dict):
    """Validate upstream geographic exports against their report and actual ABS shapes."""
    paths = {
        "gtfs": root / "data/raw/transport/gtfs.zip",
        "geo_spec": root / "config/lga_snapshot.json",
        "aliases": root / "config/lga_name_aliases_2025.csv",
        "native": root / "data/processed/geography/metro_lga_2025.gpkg",
        "crosswalk": root / "data/interim/geography/lga_crosswalk_2025.csv",
        "geo_report": root / "data/interim/geography/geography_pipeline_report.json",
        "transport_spec": root / "config/gtfs_snapshot.json",
    }
    for path in paths.values():
        if not path.is_file():
            raise FileNotFoundError(f"Missing upstream input: {path}. Complete the geography pipeline first.")
    geo_spec = load_geo_snapshot(paths["geo_spec"])
    abs_path = root / "data/raw/geography" / geo_spec["filename"]
    require(abs_path.is_file() and sha256_file(abs_path) == geo_spec["sha256"], "ABS snapshot changed.")
    require(sha256_file(paths["gtfs"]) == spec["sha256"], "GTFS fingerprint differs from the audited source.")
    with ZipFile(paths["gtfs"]) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) and set(names) == set(spec["outer_members"]), "GTFS archive inventory changed.")
    geo = read_json(paths["geo_report"])
    require(geo.get("boundary_snapshot") == geo_spec and geo.get("check_only") is False,
            "Geographic build report/configuration does not match a completed build.")
    for flag in ("gpkg_readback_matches", "geojson_readback_matches", "csv_readback_matches"):
        require(geo.get(flag) is True, f"Geography checkpoint incomplete: {flag}")
    geo_hashes = {k.replace("\\", "/"): v for k, v in geo.get("output_sha256", {}).items()}
    for key in ("native", "crosswalk"):
        path = paths[key]
        require(geo_hashes.get(path.relative_to(root).as_posix()) == sha256_file(path),
                f"Geography export no longer matches its report: {path.name}")
    native = gpd.read_file(paths["native"], layer="metro_lga_2025", engine="pyogrio")
    for key in (CODE, NAME):
        native[key] = native[key].astype("string")
    require(len(native) == 31 and native.crs.to_epsg() == 7844, "Unexpected native geography scope or CRS.")
    crosswalk = pd.read_csv(paths["crosswalk"], dtype="string", keep_default_na=False)
    require(crosswalk.columns.tolist() == CROSSWALK_COLUMNS and len(crosswalk) == 31, "Crosswalk schema/scope changed.")
    rebuilt = build_crosswalk(crosswalk[["rental_area_name","source_region"]], native[[CODE,NAME]], load_aliases(paths["aliases"]))
    pd.testing.assert_frame_equal(crosswalk.sort_values("rental_area_name").reset_index(drop=True),
                                  rebuilt.astype("string").sort_values("rental_area_name").reset_index(drop=True), check_exact=True)
    # Do not rely solely on a mutable local report. Compare shapes to the pinned ABS source.
    councils, _, _ = read_boundaries(abs_path, geo_spec)
    by_code = councils.set_index("LGA_CODE25")
    require(set(native[CODE]) == set(crosswalk[CODE]) and native[CODE].is_unique, "LGA inventory changed.")
    for row in native.itertuples(index=False):
        code = getattr(row, CODE)
        require(code in by_code.index and getattr(row, NAME) == by_code.loc[code, "LGA_NAME25"], "Wrong ABS code/name.")
        require(row.geometry.equals_exact(by_code.loc[code].geometry, 0.0), f"Native geometry differs: {code}")
    tracked = set(paths.values()) | {abs_path}
    # Notebook audit is provenance evidence, not an audit that this refactor pretends to rerun.
    audit_path = root / "data/interim/gtfs_audit/audit_summary.json"
    if audit_path.is_file():
        audit = read_json(audit_path)
        require(audit.get("source", {}).get("sha256") == spec["sha256"] and audit.get("source_unchanged") is True,
                "Existing GTFS audit belongs to another/incomplete snapshot.")
        require(audit.get("proposed_service_date") == spec["service_date"], "Audit date differs.")
        tracked.add(audit_path)
    for folder in (root/"notebooks", root/"docs", root/"data/interim/gtfs_spatial", root/"data/interim/gtfs_service"):
        if folder.is_dir():
            tracked.update(p for p in folder.iterdir() if p.is_file())
    for rel in ("data/processed/rent_quarterly.csv","data/processed/rent_quarterly.parquet","data/processed/rent_quality_report.json"):
        if (root/rel).is_file(): tracked.add(root/rel)
    return paths["gtfs"], native, crosswalk, {p:sha256_file(p) for p in tracked}


def csv_text_frame(table: pd.DataFrame) -> pd.DataFrame:
    """Canonical value view using the notebook's CSV serialization, not file bytes."""
    return pd.read_csv(io.StringIO(table.to_csv(index=False, lineterminator="\n")), dtype="string", keep_default_na=False)


def check_csv(path: Path, expected: pd.DataFrame) -> None:
    actual = pd.read_csv(path, dtype="string", keep_default_na=False)
    try:
        pd.testing.assert_frame_equal(actual, csv_text_frame(expected), check_exact=True)
    except AssertionError as error:
        raise ValueError(f"CSV differs from rebuilt values/schema/order: {path}. No outputs replaced.") from error


def restore_point_attributes(table: pd.DataFrame, expected: pd.DataFrame) -> pd.DataFrame:
    require(set(table.columns) == set(expected.columns), "GeoPackage attribute columns changed.")
    restored = table[expected.columns].copy()
    for col in restored:
        if pd.api.types.is_bool_dtype(expected[col].dtype):
            text = restored[col].astype("string").str.lower()
            require(text.isin(["true","false","1","0"]).all(), f"Invalid boolean field {col}")
            restored[col] = text.isin(["true","1"])
        elif pd.api.types.is_integer_dtype(expected[col].dtype):
            restored[col] = pd.to_numeric(restored[col], errors="raise").astype(expected[col].dtype)
        elif pd.api.types.is_float_dtype(expected[col].dtype):
            restored[col] = pd.to_numeric(restored[col], errors="raise").astype(expected[col].dtype)
        else:
            restored[col] = restored[col].astype("string").fillna("")
    return restored


def check_points(path: Path, expected: gpd.GeoDataFrame) -> None:
    actual = gpd.read_file(path, layer="stop_lga_matches", engine="pyogrio")
    require(actual.crs == expected.crs and len(actual) == len(expected), "Point GeoPackage CRS/row count changed.")
    require(actual.stop_key.is_unique and set(actual.stop_key) == set(expected.stop_key), "GeoPackage stop keys changed.")
    actual = actual.set_index("stop_key").loc[expected.stop_key].reset_index()
    exp = pd.DataFrame(expected.drop(columns="geometry"))
    restored = restore_point_attributes(pd.DataFrame(actual.drop(columns="geometry")), exp)
    pd.testing.assert_frame_equal(restored, exp, check_exact=True)
    require(all(a.equals_exact(b,0.0) for a,b in zip(actual.geometry, expected.geometry)), "Point coordinates changed on read-back.")


def compare_folder(folder: Path, tables: dict[str, pd.DataFrame], points=None) -> list[str]:
    """Compare all existing files; partial references are reported, never called complete."""
    compared=[]
    for name,table in tables.items():
        path=folder/name
        if path.exists():
            require(path.is_file(), f"Output path is not a file: {path}")
            check_csv(path,table); compared.append(str(path))
    if points is not None and (folder/POINT_NAME).exists():
        check_points(folder/POINT_NAME,points);compared.append(str(folder/POINT_NAME))
    return compared


def registry_update_text(path: Path, spec: dict) -> str:
    """Change only dataset_id=gtfs; keep custom fields, notes and other datasets."""
    with path.open(encoding="utf-8-sig",newline="") as handle:
        reader=csv.DictReader(handle);fields=list(reader.fieldnames or []);rows=list(reader)
    require(len(fields)==len(set(fields)) and {"dataset_id","status"}.issubset(fields), "Invalid registry header.")
    require(all(None not in row and all(v is not None for v in row.values()) for row in rows), "Malformed registry rows.")
    matches=[row for row in rows if row['dataset_id']=='gtfs']
    require(len(matches)==1,"Expected exactly one GTFS registry record.")
    changes={
        'status':'service_indicators_validated', 'source_filename':spec['filename'], 'source_sha256':spec['sha256'],
        'service_date':spec['service_date'], 'service_timezone':spec['timezone'], 'boundary_year':'2025',
        'selected_feed_ids':'2;3;4',
        'processed_scope':'31 reviewed LGAs; regular-pickup non-terminal scheduled events; service day and 07:00-09:00; labelled replacements separate',
        'processed_file':'data/processed/transport/service/lga_service_indicators.csv',
        'build_command':'python scripts/build_transport.py --update-registry',
    }
    for k in changes:
        if k not in fields:fields.append(k)
    matches[0].update(changes)
    stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=fields,lineterminator='\n');writer.writeheader();writer.writerows(rows)
    return stream.getvalue()


def save_registry(root: Path, new_text: str, previous_hash: str) -> None:
    path=root/'docs/data_registry.csv'
    require(sha256_file(path)==previous_hash,"Registry changed during build; do not overwrite concurrent edits.")
    if path.read_bytes()==new_text.encode('utf-8'):return
    backup=root/'data/interim/registry_backups'/f'data_registry_before_transport_{previous_hash}.csv'
    backup.parent.mkdir(parents=True,exist_ok=True)
    if not backup.exists():
        with backup.open('xb') as handle:
            handle.write(path.read_bytes())
    with TemporaryDirectory(prefix='.registry-',dir=path.parent) as temporary:
        staged=Path(temporary)/path.name;staged.write_text(new_text,encoding='utf-8')
        require(sha256_file(path)==previous_hash,"Registry changed before replacement.")
        staged.replace(path)


def export_outputs(root: Path, spatial: dict, points: gpd.GeoDataFrame, services: dict,
                   report: dict, hashes: dict[Path,str], *, check_only: bool) -> dict:
    """All comparisons occur before writes. Only new processed-output files are replaced.

    Per-file atomic replacements are NOT a multi-file transaction; the report is
    published last. Avoid simultaneous builds; a crash requires review/rebuild.
    """
    require(tuple(spatial)==SPATIAL_NAMES and tuple(services)==SERVICE_NAMES,"Unexpected export inventory.")
    dest=root/'data/processed/transport'
    references=compare_folder(root/'data/interim/gtfs_spatial',spatial,points)
    references+=compare_folder(root/'data/interim/gtfs_service',services)
    old=compare_folder(dest/'spatial',spatial,points)+compare_folder(dest/'service',services)
    report=dict(report,notebook_exports_compared=[str(Path(p).relative_to(root)) for p in references],
                previous_pipeline_exports_compared=[str(Path(p).relative_to(root)) for p in old],
                check_only=check_only)
    print(f'Notebook exports matched: {len(references)}/18',flush=True)
    print(f'Previous pipeline exports matched: {len(old)}/18',flush=True)
    if len(references)!=18:print('Some notebook reference files are absent; absent files were not compared.',flush=True)
    # Snapshot destination content as well so concurrent edits are not silently clobbered.
    prior={p:sha256_file(p) for p in dest.rglob('*') if p.is_file()} if dest.exists() else {}
    unchanged(hashes);unchanged(prior)
    if check_only:
        report['project_output_files_written']=0;return report
    parent=root/'data/processed';parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix='.transport-stage-',dir=parent) as temp:
        stage=Path(temp);file_list=[];schemas={}
        for folder,tables in [('spatial',spatial),('service',services)]:
            (stage/folder).mkdir()
            for name,table in tables.items():
                rel=Path(folder)/name;path=stage/rel
                table.to_csv(path,index=False,encoding='utf-8',lineterminator='\n');check_csv(path,table)
                file_list.append(rel);schemas[rel.as_posix()]={'rows':len(table),'columns':table.columns.tolist()}
        point_rel=Path('spatial')/POINT_NAME
        pyogrio.write_dataframe(points,stage/point_rel,driver='GPKG',layer='stop_lga_matches',geometry_type='Point')
        check_points(stage/point_rel,points);file_list.append(point_rel)
        report.update(output_sha256={p.as_posix():sha256_file(stage/p) for p in file_list},output_schemas=schemas,
                      csv_readback_matches=True,gpkg_readback_matches=True,project_output_files_written=len(file_list)+1)
        (stage/REPORT_NAME).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        require(read_json(stage/REPORT_NAME)==report,'Pipeline report read-back mismatch.')
        unchanged(hashes);unchanged(prior)
        for rel in [*file_list,Path(REPORT_NAME)]:
            target=dest/rel;target.parent.mkdir(parents=True,exist_ok=True);(stage/rel).replace(target)
    return report


def run_transport(root: Path, *, check_only: bool=False, update_registry: bool=False, chunk_rows: int=100_000) -> dict:
    require(not(check_only and update_registry),'--check-only cannot update the registry.')
    require(type(chunk_rows) is int and 1<=chunk_rows<=1_000_000,'Use a chunk size from 1 to 1000000.')
    root=Path(root).resolve();spec=load_transport_snapshot(root/'config/gtfs_snapshot.json')
    # Disable optional grid downloads during this offline analysis; restore caller's setting.
    network_before=pyproj.network.is_network_enabled();pyproj.network.set_network_enabled(False)
    try:
        print('Verifying pinned sources and validated geography...',flush=True)
        src,native,crosswalk,hashes=read_inputs(root,spec)
        registry=root/'docs/data_registry.csv';registry_hash=sha256_file(registry) if update_registry else None
        new_registry=registry_update_text(registry,spec) if update_registry else None
        print('Reading feed metadata and rebuilding stop assignments...',flush=True)
        tables={f:read_feed_tables(src,f) for f in spec['feed_ids']}
        for f,t in tables.items():
            require(len(t['stops.txt'])==spec['location_counts'][f],f'Feed {f}: changed stop inventory.')
        spatial,points,spatial_quality=build_spatial({f:t['stops.txt'] for f,t in tables.items()},native,crosswalk,spec)
        active,active_summary=build_active_trips(tables,date.fromisoformat(spec['service_date']))
        for row in active_summary.itertuples(index=False):
            require(row.active_trip_records==spec['active_trip_counts'][row.feed_id] and row.labelled_replacement_trip_records==spec['replacement_trip_counts'][row.feed_id],f'Feed {row.feed_id}: active-trip inventory changed.')
        active=categorize_trips(active)
        print('Scanning active-trip stop times one feed at a time...',flush=True)
        results={}
        for f in spec['feed_ids']:
            results[f]=scan_service_feed(src,f,active.loc[active.feed_id.eq(f)].copy(),spatial['stop_lga_matches.csv'],spec['scan_rows'][f],chunk_rows)
        services=combine_service_results(results,active,crosswalk[[CODE,NAME,'rental_area_name']],date.fromisoformat(spec['service_date']),sum(spec['scan_rows'].values()))
        network=services['feed_service_summary.csv'];scans=services['scan_summary.csv']
        full=network.loc[network.window.eq('service_day')];am=network.loc[network.window.eq('am_peak_0700_0900')]
        observed={'source_rows':int(scans.source_stop_time_rows_scanned.sum()),'active_trips':len(active),'active_events':int(scans.active_stop_time_rows.sum()),
                  'service_day_events':int(full.eligible_departure_events.sum()),'am_events':int(am.eligible_departure_events.sum()),'am_trips':int(am.unique_trip_records.sum()),'lga_rows':len(services['lga_service_indicators.csv'])}
        require(observed==spec['expected_totals'],'Aggregate checkpoint differs from the audited notebook. Retain the sources and inspect the change.')
        report={'created_at_utc':datetime.now(timezone.utc).isoformat(),'builder':'scripts/build_transport.py','transport_snapshot':spec,
                'input_sha256':{p.relative_to(root).as_posix():h for p,h in hashes.items()},'spatial_quality':spatial_quality,'quality':observed,
                'counts_reconciled':True,'upstream_inputs_unchanged':True,'notebook_reports_unchanged':True,
                'audit_scope_note':'Uses the pinned archive audited in notebook 05. Rebuilds notebooks 06/07. Full 05 certification and inactive-trip checks are not rerun.',
                'versions':{'python':sys.version.split()[0],'pandas':pd.__version__,'geopandas':gpd.__version__,'shapely':shapely.__version__,'pyproj':pyproj.__version__}}
        print('Comparing all rebuilt values with available notebook and pipeline exports...',flush=True)
        report=export_outputs(root,spatial,points,services,report,hashes,check_only=check_only)
        unchanged(hashes)
        if update_registry:
            save_registry(root,new_registry,registry_hash)
            print('Data registry: GTFS row updated; other dataset records preserved',flush=True)
        print('TRANSPORT CHECK-ONLY PASSED' if check_only else 'TRANSPORT PIPELINE CHECKPOINT PASSED')
        print('Service date: 2026-10-13 (Australia/Melbourne)')
        print('Stop/platform records: 25031 | Within selected LGAs: 21426 | Outside retained: 3605')
        for label,key in [('Source stop-time rows scanned','source_rows'),('Active trip records','active_trips'),('Active stop-time rows','active_events'),('Counted service-day departure events','service_day_events'),('Counted AM departure events','am_events'),('Distinct AM trip records across the study area','am_trips'),('LGA/category/window rows','lga_rows')]:
            print(f'{label}: {observed[key]}')
        print('Independent spatial and count checks: passed')
        print('Project outputs written: 0' if check_only else '17 CSV tables and point GeoPackage read-back: matched')
        print('Original sources, notebook outputs and earlier reports: unchanged')
        if not check_only:print('Saved: data/processed/transport/transport_pipeline_report.json')
        return report
    finally:
        pyproj.network.set_network_enabled(network_before)
