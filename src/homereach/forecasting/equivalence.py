"""Read-only equivalence check against an ALREADY completed notebook 13.

No first-time scoring mode, export flag, tuning option, Git write or network call.
Fails closed when the original evidence, plan or current history disagree.
"""
from __future__ import annotations
from pathlib import Path, PurePosixPath
from typing import Any
import hashlib
import importlib.util
import json
import os
import subprocess

import numpy as np
import pandas as pd

from homereach.io.dffh_rent import COLUMN_ORDER, read_panel_csv
from .core import require, MODELS, KEY, SERIES, FINAL_QUARTERS, CANDIDATE, LAST, metrics
from .evaluation import TABLE_KEYS, evaluate_fixed

LOCK_COMMIT = 'd0858bdf46fa6b15c34731f0e41873fb5a2ccfe9'
PROTOCOL_SHA = 'f0168e345aafba1a64b883bef1fe351185d7cf57575ce870f252301b484d1495'
NOTEBOOK_SOURCE_SHA = 'cc28178d9974d370bf5fecd3c5c279ee3e3f8e826148b17b964d60d6c57160e9'
PROTOCOL_FILE = 'config/rental_final_evaluation_protocol.json'
REFERENCE_DIR = 'data/interim/rental_final_evaluation'
EVIDENCE = {
    'baseline': ('rental_forecast_baselines', 'baseline_manifest.json'),
    'ridge': ('rental_ridge_validation', 'ridge_manifest.json'),
    'diagnostics': ('rental_ridge_diagnostics', 'diagnostic_manifest.json'),
    'correction': ('rental_correction_validation', 'correction_manifest.json'),
}


def fingerprint(path: Path) -> str:
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def canonical_hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f'Nonfinite JSON constant: {value}')


def load_json(path: Path) -> dict:
    value = json.loads(Path(path).read_text(encoding='utf-8-sig'),
                       object_pairs_hook=_pairs, parse_constant=_reject_constant)
    require(isinstance(value, dict), f'Expected a JSON object: {path.name}')
    return value


def checked_child(directory: Path, name: str) -> Path:
    """Reject absolute paths, traversal, symlink escapes and Windows separators."""
    require(isinstance(name, str) and name and '\\' not in name and ':' not in name,
            'Unsafe evidence path.')
    pure = PurePosixPath(name)
    require(not pure.is_absolute() and '..' not in pure.parts, 'Unsafe evidence path.')
    path = directory.joinpath(*pure.parts)
    require(path.resolve().is_relative_to(directory.resolve()), 'Evidence path leaves its directory.')
    return path


def git_bytes(root: Path, *args: str) -> bytes:
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                            timeout=30, env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})
    require(result.returncode == 0,
            f'Git check failed: {" ".join(args)}: {result.stderr.decode(errors="replace").strip()}')
    return result.stdout


def verify_lock(root: Path) -> tuple[dict, dict]:
    """Compare the original gate to its lock commit before importing its functions."""
    gate_path = root/'scripts/verify_rental_final_protocol.py'
    committed = git_bytes(root, 'show', f'{LOCK_COMMIT}:scripts/verify_rental_final_protocol.py')
    require(gate_path.read_text(encoding='utf-8-sig').replace('\r\n', '\n') ==
            committed.decode('utf-8-sig').replace('\r\n', '\n'), 'Original protocol verifier changed.')
    loader = importlib.util.spec_from_file_location('_homereach_frozen_gate', gate_path)
    require(loader is not None and loader.loader is not None, 'Cannot import original protocol gate.')
    gate = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(gate)
    lock = gate.verify_project(root, require_committed=True)
    require(lock['protocol_commit'] == LOCK_COMMIT, 'Pre-scoring lock commit differs.')
    git_bytes(root, 'merge-base', '--is-ancestor', LOCK_COMMIT, 'HEAD')
    for relative in gate.LOCK_FILES:
        require(gate.same_content(relative, (root/relative).read_bytes(),
                                 git_bytes(root, 'show', f'{LOCK_COMMIT}:{relative}')),
                f'Frozen file changed: {relative}')
    plan = load_json(root/PROTOCOL_FILE)
    require(canonical_hash(plan) == PROTOCOL_SHA == lock['protocol_sha256'], 'Frozen protocol differs.')
    return plan, lock


def schema_for(frame: pd.DataFrame) -> dict[str, str]:
    return {name: ('int64' if pd.api.types.is_integer_dtype(dtype) else
                   'float64' if pd.api.types.is_float_dtype(dtype) else 'string')
            for name, dtype in frame.dtypes.items()}


def read_saved(path: Path, schema: dict[str, str]) -> pd.DataFrame:
    require(isinstance(schema, dict) and schema and set(schema.values()) <= {'string', 'int64', 'float64'},
            f'Unsupported saved schema: {path.name}')
    nulls = {col: [''] for col, kind in schema.items() if kind == 'float64'}
    frame = pd.read_csv(path, dtype=schema, keep_default_na=False, na_values=nulls)
    require(frame.columns.tolist() == list(schema), f'Saved schema/order mismatch: {path.name}')
    return frame


def compare_table(rebuilt: pd.DataFrame, saved: pd.DataFrame, keys: list[str], label: str) -> None:
    """Exact identifiers/counts/text; documented float tolerance, never rounded scores."""
    require(rebuilt.columns.tolist() == saved.columns.tolist() and len(rebuilt) == len(saved),
            f'{label}: shape/columns differ.')
    if keys:
        require(not rebuilt.duplicated(keys).any() and not saved.duplicated(keys).any(), f'{label}: duplicate key.')
        a = rebuilt.sort_values(keys, kind='stable').reset_index(drop=True)
        b = saved.sort_values(keys, kind='stable').reset_index(drop=True)
    else:
        require(len(rebuilt) == 1, f'{label}: expected one ungrouped summary row.')
        a, b = rebuilt.reset_index(drop=True), saved.reset_index(drop=True)
    for col, kind in schema_for(rebuilt).items():
        try:
            if kind == 'float64':
                np.testing.assert_array_equal(a[col].isna(), b[col].isna())
                np.testing.assert_allclose(a[col].to_numpy(float), b[col].to_numpy(float),
                                          rtol=1e-10, atol=1e-9, equal_nan=True)
            elif kind == 'int64':
                np.testing.assert_array_equal(a[col].to_numpy(), b[col].to_numpy())
            else:
                require(a[col].astype('string').equals(b[col].astype('string')), 'Text differs.')
        except (AssertionError, ValueError) as error:
            raise ValueError(f'{label}: column {col} differs; preserve the evidence and investigate.') from error


def verify_manifest_files(directory: Path, manifest: dict) -> None:
    require(isinstance(manifest.get('output_sha256'), dict) and manifest['output_sha256'], 'Missing output fingerprints.')
    for relative, digest in manifest['output_sha256'].items():
        path = checked_child(directory, relative)
        require(isinstance(digest, str) and len(digest) == 64, 'Malformed output digest.')
        require(path.is_file() and fingerprint(path) == digest, f'Saved evidence changed: {path}')


def load_completed_evidence(root: Path, plan: dict) -> tuple[pd.DataFrame, dict, dict[str, pd.DataFrame]]:
    """Require the original complete final run; do not bootstrap missing evidence."""
    directory = root/REFERENCE_DIR
    path = directory/'final_manifest.json'
    require(path.is_file(), 'Completed notebook 13 evidence is required. Do not create or delete evidence to bypass this check.')
    final = load_json(path)
    require(final['protocol_commit'] == LOCK_COMMIT and final['protocol_sha256'] == PROTOCOL_SHA,
            'Saved final result uses another protocol.')
    require(final['notebook_source_sha256'] == NOTEBOOK_SOURCE_SHA, 'Saved final run used different notebook source.')
    notebook = load_json(root/'notebooks/13_rental_final_evaluation.ipynb')
    cells = [{'cell_type': c['cell_type'], 'source': ''.join(c['source']).replace('\r\n', '\n')}
             for c in notebook['cells']]
    require(canonical_hash({'cells': cells}) == NOTEBOOK_SOURCE_SHA, 'Notebook 13 source changed; outputs/metadata are allowed.')
    require(final['quality']['csv_readback_matches'] is True, 'Final result does not record successful CSV read-back.')
    require(set(final['output_schemas']) == set(TABLE_KEYS), 'Expected all 13 saved table schemas.')
    require(set(TABLE_KEYS).issubset(final['output_sha256']), 'Missing table fingerprints.')
    verify_manifest_files(directory, final)
    require(canonical_hash(load_json(directory/'final_protocol.json')) == PROTOCOL_SHA, 'Saved protocol copy differs.')
    frozen_report = directory/'final_evaluation_report.md'
    require(fingerprint(frozen_report) == final['report_sha256'], 'Original report fingerprint differs.')
    local_report = root/'docs/rental_final_evaluation.md'
    require(local_report.read_text(encoding='utf-8-sig').replace('\r\n', '\n') ==
            frozen_report.read_text(encoding='utf-8-sig').replace('\r\n', '\n'), 'Final prose report differs.')
    source = plan['source']
    csv_path = root/source['processed_input']
    quality = load_json(root/source['local_integrity_report'])
    spec = load_json(root/'config/rent_snapshot.json')
    require(spec['sha256'] == quality['source']['sha256'] == final['source_workbook_sha256'] == source['sha256'],
            'Source workbook vintage differs.')
    digest = fingerprint(csv_path)
    require(quality['output_sha256'][csv_path.name] == final['input_csv_sha256'] == digest, 'Rental CSV fingerprint differs.')
    require(quality['csv_readback_matches'] is True and quality['quality']['source_values_verified'] == 6572,
            'Rental audit is incomplete.')
    panel = read_panel_csv(csv_path)
    require(panel.columns.tolist() == COLUMN_ORDER and len(panel) == 3286, 'Rental schema/size differs.')
    require(not panel.duplicated(SERIES + ['quarter']).any(), 'Duplicate input history key.')
    for field, value in {'property_type': '2 bedroom flats', 'area_type': 'LGA',
                         'source_file': source['filename'], 'source_sheet': spec['sheet'],
                         'source_reporting_quarter': '2025Q3'}.items():
        require(panel[field].eq(value).all(), f'Rental scope differs: {field}')
    for field in ('median_weekly_rent', 'published_count'):
        require(np.isfinite(panel[field].to_numpy(float)).all() and panel[field].gt(0).all(), f'Invalid {field}.')
    periods = pd.PeriodIndex(panel.quarter, freq='Q-DEC')
    np.testing.assert_array_equal(pd.DatetimeIndex(panel.quarter_end).as_unit('ns').asi8,
                                 periods.to_timestamp(how='end').normalize().as_unit('ns').asi8)
    wanted = pd.period_range('1999Q2', '2025Q3', freq='Q-DEC').astype(str).tolist()
    require(panel.rental_area_name.nunique() == 31, 'LGA coverage differs.')
    for _, group in panel.groupby(SERIES, sort=True):
        require(sorted(group.quarter.tolist()) == wanted, 'Quarter coverage differs.')
    for label, (folder, filename) in EVIDENCE.items():
        path = root/'data/interim'/folder/filename
        require(fingerprint(path) == final['earlier_manifest_sha256'][label], f'{label} manifest changed.')
        prior = load_json(path)
        verify_manifest_files(path.parent, prior)
    saved = {name: read_saved(directory/name, final['output_schemas'][name]) for name in TABLE_KEYS}
    return panel, final, saved


def snapshot(root: Path) -> dict[str, str]:
    """Capture relevant files and detect additions/deletions, excluding Python caches."""
    paths = set()
    for folder in ['config', 'app', 'deploy', 'src', 'scripts', 'tests', 'docs', 'notebooks',
                   REFERENCE_DIR, *['data/interim/'+v[0] for v in EVIDENCE.values()]]:
        paths.update(p for p in (root/folder).rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and p.suffix != '.pyc')
    for relative in ['data/processed/rent_quarterly.csv', 'data/processed/rent_quality_report.json',
                     'data/processed/rent_quarterly.parquet']:
        if (root/relative).is_file():
            paths.add(root/relative)
    return {p.relative_to(root).as_posix(): fingerprint(p) for p in sorted(paths)}


def verify_equivalence(root: Path, *, progress=print) -> dict[str, Any]:
    """Recompute and compare, with no write path. Must already have final evidence."""
    root = Path(root).resolve()
    plan, lock = verify_lock(root)
    before = snapshot(root)
    progress('Verifying the completed final-evaluation evidence and input fingerprints...')
    try:
        panel, final, saved = load_completed_evidence(root, plan)
        progress('Recomputing the four FROZEN methods; this is not a new independent final test.')
        tables, checks = evaluate_fixed(panel, target_quarters=plan['periods']['final_target_quarters'],
                                       minimum_examples=plan['rolling_evaluation']['minimum_training_examples'], progress=progress)
        for name, frame in tables.items():
            require(schema_for(frame) == final['output_schemas'][name], f'Output schema changed: {name}')
            compare_table(frame, saved[name], TABLE_KEYS[name], name)
        require(checks == {'forecasts': 992, 'trained_fits': 496, 'lag_checks': 97712,
                           'change_checks': 73284, 'baseline_source_checks': 496,
                           'source_lineage_rows': 992, 'coefficient_rows': 3224}, 'Fixed-scope counts differ.')
        after_lock_plan, after_lock = verify_lock(root)
        require(lock == after_lock and plan == after_lock_plan, 'Git HEAD or protocol changed during comparison.')
    finally:
        require(snapshot(root) == before, 'Protected files changed during the check. Preserve and investigate.')
    return {'tables_matched': len(tables), **checks, 'protocol_commit': LOCK_COMMIT,
            'original_execution_commit': final['execution_commit'], 'execution_commit': lock['head_commit'],
            'reference_manifest_sha256': fingerprint(root/REFERENCE_DIR/'final_manifest.json'),
            'metrics': tables['final_metrics_overall.csv'].to_dict('records'),
            'files_written': 0, 'independent_final_tests_added': 0}
