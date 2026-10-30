"""Freeze a verified local explorer bundle for portable, read-only hosting.

The local loader is NOT relaxed. Packaging requires its existing source/report
checks. The release loader verifies only the explicitly packaged snapshot, not
live upstream files. SHA-256 detects byte changes; it is not a digital signature.
No raw data, credentials, stop/trip-level files or arbitrary directory copies.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
import hashlib
import json
import re
import shutil
import pandas as pd
import numpy as np

from .analysis import CODE, AM_WINDOW, DAY_WINDOW, RENT_QUARTER, SERVICE_DATE, TIMEZONE, CATEGORY_LABELS, fingerprint, read_json, require
from .bundle import (ExplorerBundle, GEOJSON, MANIFEST, TABLE_NAMES, bundle_signature,
                     load_bundle, read_table, validate_bundle_tables, validate_geometry_payload)

RELEASE_MANIFEST = 'release_manifest.json'
ATTRIBUTION_FILE = 'source_attribution.json'
DATA_NAMES = (*TABLE_NAMES, GEOJSON)
PAYLOAD_NAMES = (*DATA_NAMES, ATTRIBUTION_FILE)
RELEASE_NAMES = (*PAYLOAD_NAMES, RELEASE_MANIFEST)
MAX_FILE_BYTES = 40 * 1024 * 1024
MAX_TOTAL_BYTES = 80 * 1024 * 1024
HEX = re.compile(r'[0-9a-f]{64}')
LICENSE_URL = 'https://creativecommons.org/licenses/by/4.0/'
ATTRIBUTIONS = {
    'reviewed_on': '2026-10-26',
    'licence_scope': 'Source data only; not logos, website design or HomeReach source-code licensing.',
    'endorsement': 'Independent student project. No endorsement by the source publishers is implied.',
    'sources': [
        {'component': 'rent', 'publisher': 'Homes Victoria / Department of Families, Fairness and Housing, State of Victoria',
         'dataset': 'Quarterly median rents by Local Government Area, September quarter 2025',
         'source_url': 'https://www.dffh.vic.gov.au/publications/rental-report',
         'licence_evidence': 'https://discover.data.vic.gov.au/dataset/rental-report-quarterly-quarterly-median-rents-by-lga',
         'licence': 'CC BY 4.0', 'licence_url': LICENSE_URL,
         'changes': 'Selected 31 source-group metropolitan LGAs and 2 bedroom flats; reshaped and joined by reviewed identifiers. Source rents and cell references retained.'},
        {'component': 'transport', 'publisher': 'Department of Transport and Planning, State of Victoria',
         'dataset': 'Transport Victoria GTFS Schedule; audited archive; service date 13 October 2026',
         'source_url': 'https://opendata.transport.vic.gov.au/dataset/gtfs-schedule',
         'licence_evidence': 'https://opendata.transport.vic.gov.au/dataset/gtfs-schedule',
         'licence': 'CC BY 4.0', 'licence_url': LICENSE_URL,
         'changes': 'Derived LGA-level aggregates for feeds 2, 3 and 4 after calendar, pickup, terminal and spatial rules. Raw GTFS, trip IDs and stop IDs are not in this release.'},
        {'component': 'boundaries', 'publisher': 'Australian Bureau of Statistics, Commonwealth of Australia',
         'dataset': 'ASGS Edition 3, Local Government Areas 2025, GDA2020',
         'source_url': 'https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs/edition-3-july-2021-june-2026/access-and-downloads/digital-boundary-files',
         'licence_evidence': 'https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs/edition-3-july-2021-june-2026/access-and-downloads/digital-boundary-files',
         'licence': 'CC BY 4.0', 'licence_url': LICENSE_URL,
         'changes': 'Selected 31 reviewed LGAs, transformed to WGS84 for web display. Statistical, not legal, boundaries; no simplification or repair.'},
    ],
}


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')


def content_id(hashes: dict[str, str]) -> str:
    return hashlib.sha256(canonical_json(hashes)).hexdigest()


def _file(path: Path) -> None:
    require(not path.is_symlink() and path.is_file(), f'Missing file or unsupported symlink: {path.name}')
    require(0 < path.stat().st_size <= MAX_FILE_BYTES, f'Unexpected file size: {path.name}')


def _scope(scope: dict) -> None:
    expected = {'rental_quarter': RENT_QUARTER, 'transport_service_date': SERVICE_DATE,
                'timezone': TIMEZONE, 'property_type': '2 bedroom flats', 'boundary_year': 2025,
                'lga_count': 31, 'selected_feeds': ['2', '3', '4'], 'score_or_prediction': False}
    require(isinstance(scope, dict), 'Missing release scope.')
    require(all(scope.get(k) == v for k, v in expected.items()), 'Release scope differs from the reviewed snapshots.')


def validate_release_tables(tables: dict[str, pd.DataFrame]) -> None:
    """Existing bundle checks plus relationships needed by the public reader."""
    validate_bundle_tables(tables)
    areas = tables['rent_transport_comparison.csv']
    require(areas[CODE].astype('string').str.fullmatch(r'2[0-9]{4}').all(), 'Invalid release LGA codes.')
    require(areas.rental_area_name.is_unique and areas.abs_lga_name.is_unique, 'Duplicate release area names.')
    for name in TABLE_NAMES:
        require(not any(c in tables[name] for c in ('trip_id', 'stop_id', 'trip_key', 'stop_key', 'latitude', 'longitude')),
                f'Unexpected record-level data in {name}.')
    history = tables['rental_history.csv']
    require(not history.duplicated([CODE, 'quarter', 'property_type']).any(), 'Duplicate rental history key.')
    expected_quarters = pd.period_range('1999Q2', RENT_QUARTER, freq='Q').astype(str).tolist()
    for _, group in history.groupby(CODE, sort=False):
        require(group.sort_values('quarter')['quarter'].tolist() == expected_quarters, 'Incomplete rental history sequence.')
    actual = pd.DatetimeIndex(history['quarter_end']).as_unit('ns')
    expected = pd.PeriodIndex(history['quarter'], freq='Q').to_timestamp(how='end').normalize().as_unit('ns')
    require(np.array_equal(actual.asi8, expected.asi8), 'History quarter/end-date mismatch.')
    latest = history.loc[history.quarter.eq(RENT_QUARTER)].set_index(CODE)
    for c in ['median_weekly_rent', 'published_count', 'rental_area_name', 'source_median_cell', 'source_count_cell']:
        require(areas.set_index(CODE)[c].sort_index().equals(latest[c].sort_index()), f'Latest rental history differs at {c}.')
    categories = tables['lga_service_categories.csv']
    require(not categories.duplicated([CODE, 'service_category', 'window']).any(), 'Duplicate category/window key.')
    require(set(categories[CODE]) == set(areas[CODE]) and set(categories.service_category) == set(CATEGORY_LABELS)
            and set(categories.window) == {AM_WINDOW, DAY_WINDOW}, 'Incomplete category scope.')
    require(categories.groupby(CODE).size().eq(8).all(), 'Incomplete LGA category grid.')
    am = categories.loc[categories.window.eq(AM_WINDOW)].groupby(CODE).eligible_departure_events.sum()
    require(np.array_equal(am.sort_index().to_numpy(), areas.set_index(CODE).am_departure_events.sort_index().to_numpy()),
            'Category/area event totals differ.')
    periods = tables['source_periods.csv']
    require(len(periods) == 3 and periods.component.is_unique
            and periods.set_index('component').period.to_dict() == {'rent': RENT_QUARTER, 'transport': SERVICE_DATE, 'boundaries': '2025'},
            'Source-period table differs from release scope.')


def _schemas(schemas: dict) -> None:
    require(isinstance(schemas, dict) and set(schemas) == set(TABLE_NAMES), 'Incomplete release table schemas.')
    allowed_types = {'string', 'str', 'object', 'string[python]', 'string[pyarrow]', 'int64', 'Int64', 'float64', 'Float64', 'bool', 'boolean', 'datetime64[ns]', 'datetime64[us]', 'datetime64[ms]', 'datetime64[s]'}
    for name, schema in schemas.items():
        columns = schema.get('columns', [])
        require(isinstance(schema.get('rows'), int) and 0 < schema['rows'] <= 5000, f'Invalid row count: {name}')
        require(isinstance(columns, list) and 0 < len(columns) <= 150 and len(set(columns)) == len(columns)
                and all(isinstance(c, str) for c in columns), f'Invalid schema columns: {name}')
        require(set(schema.get('dtypes', {})) == set(columns)
                and set(schema['dtypes'].values()) <= allowed_types, f'Unsupported CSV data types: {name}')


def release_signature(folder: Path) -> str:
    """Verify only the release. Never traverse manifest-provided file paths."""
    folder = Path(folder)
    require(folder.is_dir() and not folder.is_symlink(), 'Release data is missing. Run scripts/package_explorer.py locally.')
    require({p.name for p in folder.iterdir()} == set(RELEASE_NAMES),
            'Release inventory is incomplete or contains unapproved extra files.')
    for name in RELEASE_NAMES:
        _file(folder / name)
    require(sum((folder / n).stat().st_size for n in RELEASE_NAMES) <= MAX_TOTAL_BYTES, 'Release exceeds the reviewed size limit.')
    m = read_json(folder / RELEASE_MANIFEST)
    require(m.get('release_schema_version') == 1 and m.get('builder') == 'scripts/package_explorer.py'
            and m.get('self_contained') is True and m.get('check_only') is False,
            'Not a completed portable release.')
    _scope(m.get('scope'))
    _schemas(m.get('output_schemas'))
    hashes = m.get('output_sha256', {})
    require(isinstance(hashes, dict) and set(hashes) == set(PAYLOAD_NAMES), 'Invalid release file allowlist.')
    require(all(isinstance(h, str) and HEX.fullmatch(h) for h in hashes.values()), 'Invalid release fingerprint.')
    require(isinstance(m.get('source_bundle_manifest_sha256'), str)
            and HEX.fullmatch(m['source_bundle_manifest_sha256']), 'Missing build provenance fingerprint.')
    require(m.get('release_id') == content_id(hashes), 'Release content ID mismatch.')
    require(m.get('csv_readback_matches') is True and m.get('geojson_readback_matches') is True,
            'Release was not fully read back.')
    for name in PAYLOAD_NAMES:
        require(fingerprint(folder / name) == hashes[name], f'Release file changed: {name}. Rebuild and review; do not edit hashes.')
    attribution = read_json(folder / ATTRIBUTION_FILE)
    require(attribution == ATTRIBUTIONS, 'Source attribution differs from the reviewed release.')
    # Explicit metadata allowlist avoids publishing local paths from upstream manifests.
    allowed = {'release_schema_version', 'builder', 'self_contained', 'check_only', 'created_at_utc', 'source_bundle_created_at_utc',
               'source_bundle_manifest_sha256', 'scope', 'quality', 'notebook_tables_compared', 'output_schemas',
               'output_sha256', 'release_id', 'csv_readback_matches', 'geojson_readback_matches', 'packager_version'}
    require(set(m) == allowed, 'Release metadata contains unknown fields.')
    return fingerprint(folder / RELEASE_MANIFEST) + ':' + m['release_id']


def load_release(folder: Path, expected_signature: str | None = None) -> ExplorerBundle:
    folder = Path(folder)
    signature = release_signature(folder)
    require(expected_signature is None or signature == expected_signature, 'Release changed while opening it.')
    m = read_json(folder / RELEASE_MANIFEST)
    tables = {name: read_table(folder / name, m['output_schemas'][name]) for name in TABLE_NAMES}
    validate_release_tables(tables)
    geometry = read_json(folder / GEOJSON)
    validate_geometry_payload(geometry, tables['rent_transport_comparison.csv'])
    require(release_signature(folder) == signature, 'Release changed while it was read.')
    return ExplorerBundle(tables, geometry, m)


def package_release(root: Path, *, check_only: bool = False) -> dict:
    """Copy only the nine validated data files, then verify a standalone copy."""
    root = Path(root).resolve()
    source = root / 'data/processed/explorer'
    dest = root / 'deploy/data'
    print('Verifying the existing local explorer bundle and upstream report fingerprints...', flush=True)
    signature = bundle_signature(root)
    bundle = load_bundle(root, expected_signature=signature)
    validate_release_tables(bundle.tables)
    _scope(bundle.manifest['scope'])
    # The source filename inventory is fixed; no recursive source-folder copying.
    for name in (*DATA_NAMES, MANIFEST):
        _file(source / name)
    source_hashes = {name: fingerprint(source / name) for name in DATA_NAMES}
    payload_hashes = {**source_hashes, ATTRIBUTION_FILE: hashlib.sha256(canonical_json(ATTRIBUTIONS)).hexdigest()}
    require(sum((source / n).stat().st_size for n in DATA_NAMES) < MAX_TOTAL_BYTES - 1024*1024,
            'Source bundle is too large for this release policy.')
    existing = False
    if dest.exists():
        if any(dest.iterdir()):
            previous = load_release(dest)
            require(previous.manifest['output_sha256'] == payload_hashes,
                    'A different release already exists. Preserve it and review a new release; no force overwrite.')
            existing = True
    print('Validated release data files: 9/9', flush=True)
    print('Existing release: ' + ('identical' if existing else 'not yet packaged'), flush=True)
    quality = {k: bundle.manifest['quality'][k] for k in (
        'joined_lgas', 'unmatched_lgas', 'duplicate_codes', 'rental_history_rows', 'service_category_rows',
        'am_events', 'distinct_study_area_am_trips', 'rental_fields_preserved', 'input_files_unchanged',
        'geometry_features', 'raw_gtfs_scans')}
    result = {'check_only': check_only, 'existing_identical': existing, 'output_files_written': 0,
              'data_bytes': sum((source/n).stat().st_size for n in DATA_NAMES)}
    require(bundle_signature(root) == signature, 'Local explorer bundle changed while preparing the release.')
    if not check_only and not existing:
        dest.parent.mkdir(parents=True, exist_ok=True)
        m = {'release_schema_version': 1, 'builder': 'scripts/package_explorer.py', 'self_contained': True,
             'check_only': False, 'packager_version': '1.0.0',
             'created_at_utc': datetime.now(timezone.utc).isoformat(),
             'source_bundle_created_at_utc': bundle.manifest['created_at_utc'],
             'source_bundle_manifest_sha256': fingerprint(source / MANIFEST),
             'scope': bundle.manifest['scope'], 'quality': quality,
             'notebook_tables_compared': [n for n in TABLE_NAMES[:6] if n in bundle.manifest['notebook_tables_compared']],
             'output_schemas': bundle.manifest['output_schemas'], 'output_sha256': payload_hashes,
             'release_id': content_id(payload_hashes), 'csv_readback_matches': True, 'geojson_readback_matches': True}
        with TemporaryDirectory(prefix='.release-stage-', dir=dest.parent) as tmp:
            stage = Path(tmp) / 'data'; stage.mkdir()
            for name in DATA_NAMES:
                shutil.copyfile(source / name, stage / name)
            (stage / ATTRIBUTION_FILE).write_bytes(canonical_json(ATTRIBUTIONS))
            (stage / RELEASE_MANIFEST).write_bytes(canonical_json(m))
            # Read all CSVs/geometry and relationships before publishing; no upstream files in stage.
            released = load_release(stage)
            for name in TABLE_NAMES:
                pd.testing.assert_frame_equal(released.tables[name], bundle.tables[name], check_dtype=False, check_exact=True)
            require(released.geometry == bundle.geometry, 'Release geometry differs from local bundle.')
            require(bundle_signature(root) == signature, 'Local source changed during packaging.')
            require(not dest.exists() or not any(dest.iterdir()), 'Release destination changed during packaging.')
            if dest.exists(): dest.rmdir()  # Only the verified empty destination; never remove user data.
            stage.replace(dest)
        result['output_files_written'] = len(RELEASE_NAMES)
    if not check_only:
        released = load_release(dest)
        result['release_id'] = released.manifest['release_id']
    require(bundle_signature(root) == signature, 'Local explorer source changed.')
    print('RELEASE CHECK-ONLY PASSED' if check_only else 'RELEASE PACKAGE CHECKPOINT PASSED')
    print('Comparison LGAs: 31 | Rental history rows: 3286 | Service-category rows: 248')
    print('Rent: 2025Q3 | Transport: 2026-10-13 | Boundaries: 2025')
    print(f'Prepared data size: {result["data_bytes"]/1024/1024:.2f} MiB')
    print('Raw source files copied: 0 | Stop/trip-level files copied: 0')
    print('Local pipeline reports required by release reader: False')
    print('Local source bundle and upstream reports: unchanged')
    print('Raw GTFS scans: 0')
    print('Project outputs written:', result['output_files_written'])
    if not check_only:
        print('Eight CSVs and GeoJSON compared with local bundle: matched')
        print('Source attribution and release manifest: verified')
        print('Saved release: deploy/data')
    return result
