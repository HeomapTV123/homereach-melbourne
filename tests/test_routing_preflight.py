"""Routing input checks use tiny fictional feeds, never a real route engine or download."""
from __future__ import annotations

import builtins
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import warnings
from zipfile import ZipFile

import pytest

from homereach.routing import preflight
from homereach.transport import gtfs, service


ROOT = Path(__file__).resolve().parents[1]
PILOT_PATH = Path('config/routing_pilot.json')
SNAPSHOT_PATH = Path('config/gtfs_snapshot.json')
ARCHIVE_PATH = Path('data/raw/transport/gtfs.zip')
FEED_IDS = ('2', '3', '4')


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def tree_contents(root: Path) -> dict:
    """Capture new empty directories as well as changed, added or deleted files."""
    return {path.relative_to(root).as_posix(): path.read_bytes() if path.is_file() else None
            for path in root.rglob('*')}


@pytest.fixture(autouse=True)
def no_route_runtime_network_or_extraction(monkeypatch):
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.split('.')[0] in {'r5py', 'jpype', 'jnius'}:
            raise AssertionError('Input preflight must not import a routing/JVM runtime.')
        return original_import(name, *args, **kwargs)

    def prohibited(*args, **kwargs):
        raise AssertionError('Input preflight must not use the network or extract archives.')

    monkeypatch.setattr(builtins, '__import__', guarded_import)
    monkeypatch.setattr(socket, 'create_connection', prohibited)
    monkeypatch.setattr(socket.socket, 'connect', prohibited)
    monkeypatch.setattr(ZipFile, 'extract', prohibited)
    monkeypatch.setattr(ZipFile, 'extractall', prohibited)


@pytest.fixture
def project(tmp_path):
    for relative in (PILOT_PATH, SNAPSHOT_PATH):
        write_json(tmp_path / relative, json.loads((ROOT / relative).read_text(encoding='utf-8')))
    return tmp_path


def csv_text(columns, rows=()) -> str:
    text = io.StringIO(newline='')
    writer = csv.writer(text)
    writer.writerow(columns)
    writer.writerows(rows)
    return text.getvalue()


def feed_tables(calendar_mode='regular', timezone='Australia/Melbourne') -> dict[str, str]:
    # Identifiers deliberately collide across feeds; each feed has one active trip.
    calendar_rows = [['regular', *(['1'] * 7), '20261001', '20261031']]
    exceptions = []
    trips = [['shared-trip', 'shared-route', 'regular']]
    if calendar_mode == 'addition':
        calendar_rows = []
        exceptions = [['added-only', '20261013', '1']]
        trips = [['shared-trip', 'shared-route', 'added-only']]
    elif calendar_mode == 'removal':
        calendar_rows.append(['retained', *(['1'] * 7), '20261001', '20261031'])
        exceptions = [['regular', '20261013', '2']]
        trips.append(['retained-trip', 'shared-route', 'retained'])
    return {
        'agency.txt': csv_text(['agency_id', 'agency_timezone'], [['shared-agency', timezone]]),
        'routes.txt': csv_text(
            ['route_id', 'agency_id', 'route_short_name', 'route_long_name', 'route_type'],
            [['shared-route', 'shared-agency', 'Fixture', 'Fictional route', '3']]),
        'trips.txt': csv_text(['trip_id', 'route_id', 'service_id'], trips),
        'calendar.txt': csv_text(['service_id', *gtfs.DAYS, 'start_date', 'end_date'], calendar_rows),
        'calendar_dates.txt': csv_text(['service_id', 'date', 'exception_type'], exceptions),
        'stops.txt': csv_text(
            ['stop_id', 'stop_name', 'stop_lat', 'stop_lon', 'location_type',
             'parent_station', 'wheelchair_boarding'],
            [['shared-stop', 'Fictional stop', '-37.8', '144.9', '0', '', '0']]),
        # Header-only input makes the preflight boundary explicit: no event rows are audited.
        'stop_times.txt': csv_text(service.RAW_EVENT_COLUMNS),
    }


def install_fixture_archive(project, monkeypatch, *, calendar_mode='regular',
                            missing_outer=False, duplicate_outer=False, extra_outer=False,
                            missing_inner=None, duplicate_inner=False, frequencies=False,
                            bad_stop_header=False, empty_stop_times=False,
                            agency_timezone='Australia/Melbourne'):
    snapshot = json.loads((project / SNAPSHOT_PATH).read_text())
    members = list(snapshot['outer_members'])
    if missing_outer:
        members.remove('3/google_transit.zip')
    if duplicate_outer:
        members.append('2/google_transit.zip')
    if extra_outer:
        members.append('unexpected.txt')
    archive_path = project / ARCHIVE_PATH
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    # Duplicate-name warnings are expected only while constructing deliberately broken ZIPs.
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='Duplicate name:', category=UserWarning)
        with ZipFile(archive_path, 'w') as outer:
            for member in members:
                tables = feed_tables(calendar_mode, agency_timezone)
                if member == '2/google_transit.zip':
                    if missing_inner:
                        del tables[missing_inner]
                    if frequencies:
                        tables['frequencies.txt'] = 'trip_id,start_time,end_time,headway_secs\n'
                    if bad_stop_header:
                        tables['stop_times.txt'] = csv_text(
                            [name for name in service.RAW_EVENT_COLUMNS if name != 'departure_time'])
                    if empty_stop_times:
                        tables['stop_times.txt'] = ''
                buffer = io.BytesIO()
                with ZipFile(buffer, 'w') as inner:
                    for name, text in tables.items():
                        inner.writestr(name, text)
                    if duplicate_inner and member == '2/google_transit.zip':
                        inner.writestr('trips.txt', tables['trips.txt'])
                outer.writestr(member, buffer.getvalue())
    snapshot['sha256'] = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    snapshot['active_trip_counts'] = {feed: 1 for feed in FEED_IDS}
    snapshot['replacement_trip_counts'] = {feed: 0 for feed in FEED_IDS}
    write_json(project / SNAPSHOT_PATH, snapshot)
    # Only this fixture boundary substitutes the production pinned-contract loader.
    # Archive hashing, tables, calendar selection, namespacing and counts stay real.
    monkeypatch.setattr(preflight, 'load_transport_snapshot',
                        lambda path: json.loads(Path(path).read_text(encoding='utf-8')))
    return snapshot


def test_reviewed_config_and_missing_archive_are_read_only(project):
    before = tree_contents(project)
    config = preflight.load_pilot_config(project)
    report = preflight.check_routing_inputs(project)
    assert config['feed_ids'] == list(FEED_IDS)
    assert config['departure_times'] == ['07:00:00', '07:30:00', '08:00:00', '08:30:00']
    assert report['status'] == 'blocked'
    assert report['gtfs']['status'] == 'missing'
    assert report['gtfs']['sha256'] is None
    assert report['gtfs']['feeds'] == []
    assert report['blockers']
    assert report['project_files_written'] == report['journeys_computed'] == 0
    assert tree_contents(project) == before


def test_verified_metadata_stays_blocked_and_preserves_cross_feed_ids(project, monkeypatch):
    snapshot = install_fixture_archive(project, monkeypatch)
    before = tree_contents(project)
    report = preflight.check_routing_inputs(project)
    assert report['status'] == 'blocked'
    assert report['gtfs']['status'] == 'verified'
    assert report['gtfs']['sha256'] == snapshot['sha256']
    assert {row['feed_id']: row['active_trip_records'] for row in report['gtfs']['feeds']} == {
        '2': 1, '3': 1, '4': 1}
    assert all(row['labelled_replacement_trip_records'] == 0 for row in report['gtfs']['feeds'])
    assert all(set(service.RAW_EVENT_COLUMNS).issubset(row['stop_times_header'])
               for row in report['gtfs']['feeds'])
    blockers = ' '.join(report['blockers']).casefold()
    assert 'street-network' in blockers and 'locations' in blockers
    unvalidated = ' '.join(report['not_validated']).casefold()
    assert 'stop-time rows' in unvalidated
    assert 'connectivity' in unvalidated and 'journeys' in unvalidated
    assert report['project_files_written'] == report['journeys_computed'] == 0
    json.dumps(report, allow_nan=False)
    assert tree_contents(project) == before


@pytest.mark.parametrize('mode', ['addition', 'removal'])
def test_calendar_exceptions_determine_active_trips(project, monkeypatch, mode):
    install_fixture_archive(project, monkeypatch, calendar_mode=mode)
    report = preflight.check_routing_inputs(project)
    # Ignoring the exception yields zero (addition) or two (removal), not one.
    assert [row['active_trip_records'] for row in report['gtfs']['feeds']] == [1, 1, 1]


def test_archive_hash_mismatch_fails_without_writing(project, monkeypatch):
    install_fixture_archive(project, monkeypatch)
    with (project / ARCHIVE_PATH).open('ab') as handle:
        handle.write(b'changed source')
    before = tree_contents(project)
    with pytest.raises(ValueError):
        preflight.check_routing_inputs(project)
    assert tree_contents(project) == before


@pytest.mark.parametrize('fault', ['missing_outer', 'duplicate_outer', 'extra_outer', 'duplicate_inner'])
def test_archive_inventory_faults_rejected(project, monkeypatch, fault):
    install_fixture_archive(project, monkeypatch, **{fault: True})
    before = tree_contents(project)
    with pytest.raises(ValueError):
        preflight.check_routing_inputs(project)
    assert tree_contents(project) == before


@pytest.mark.parametrize('table', [*gtfs.TABLE_NAMES, 'stop_times.txt'])
def test_missing_required_inner_table_rejected(project, monkeypatch, table):
    install_fixture_archive(project, monkeypatch, missing_inner=table)
    with pytest.raises(ValueError):
        preflight.check_routing_inputs(project)


@pytest.mark.parametrize('options', [
    {'frequencies': True}, {'bad_stop_header': True}, {'agency_timezone': 'UTC'},
])
def test_unsupported_or_malformed_feed_rejected(project, monkeypatch, options):
    install_fixture_archive(project, monkeypatch, **options)
    with pytest.raises(ValueError):
        preflight.check_routing_inputs(project)


def test_zero_byte_stop_times_rejected_as_missing_header(project, monkeypatch):
    install_fixture_archive(project, monkeypatch, empty_stop_times=True)
    with pytest.raises(ValueError, match='missing stop-time header'):
        preflight.check_routing_inputs(project)


@pytest.mark.parametrize('field', ['active_trip_counts', 'replacement_trip_counts'])
def test_trip_inventory_must_match_snapshot(project, monkeypatch, field):
    snapshot = install_fixture_archive(project, monkeypatch)
    snapshot[field]['2'] += 1
    write_json(project / SNAPSHOT_PATH, snapshot)
    with pytest.raises(ValueError):
        preflight.check_routing_inputs(project)


@pytest.mark.parametrize('field,value', [
    ('service_date', '2026-10-14'), ('timezone', 'UTC'), ('feed_ids', ['2', '3']),
])
def test_pilot_scope_must_match_reviewed_transport_snapshot(project, field, value):
    config = json.loads((project / PILOT_PATH).read_text())
    config[field] = value
    write_json(project / PILOT_PATH, config)
    with pytest.raises(ValueError):
        preflight.load_pilot_config(project)


@pytest.mark.parametrize('departures', [
    ['06:59:59'], ['09:00:00'], ['07:60:00'], ['24:00:00'], [],
    ['07:00:00', '07:00:00'], ['08:00:00', '07:00:00'],
])
def test_invalid_departure_times_rejected(project, departures):
    config = json.loads((project / PILOT_PATH).read_text())
    config['departure_times'] = departures
    write_json(project / PILOT_PATH, config)
    with pytest.raises(ValueError):
        preflight.load_pilot_config(project)


@pytest.mark.parametrize('field,value', [
    ('sha256', '0' * 64), ('service_date', '2026-10-14'),
    ('active_trip_counts', {'2': 1, '3': 1, '4': 1}),
])
def test_production_contract_rejects_edited_pinned_snapshot(project, field, value):
    # No fixture-loader monkeypatch: exercise the repository's real audited contract.
    snapshot = json.loads((project / SNAPSHOT_PATH).read_text())
    snapshot[field] = value
    write_json(project / SNAPSHOT_PATH, snapshot)
    with pytest.raises(ValueError, match='Transport contract changed'):
        preflight.check_routing_inputs(project)


def run_cli(project):
    return subprocess.run(
        [sys.executable, str(ROOT / 'scripts/check_routing_inputs.py'),
         '--project-root', str(project), '--json'],
        capture_output=True, text=True, check=False, timeout=30,
        env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
    )


def test_cli_missing_archive_returns_blocked_exit_two(project):
    before = tree_contents(project)
    result = run_cli(project)
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report['status'] == 'blocked' and report['gtfs']['status'] == 'missing'
    assert report['project_files_written'] == report['journeys_computed'] == 0
    assert tree_contents(project) == before


def test_cli_missing_archive_does_not_import_gis_or_routing_runtime(project):
    before = tree_contents(project)
    bootstrap = """
import importlib.abc
import runpy
import sys

class RejectUnusedRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {
            'geopandas', 'pyogrio', 'pyproj', 'shapely', 'r5py', 'jpype', 'jnius',
        }:
            raise AssertionError('Input preflight must not import ' + fullname)
        return None

sys.meta_path.insert(0, RejectUnusedRuntime())
script, *arguments = sys.argv[1:]
sys.argv = [script, *arguments]
runpy.run_path(script, run_name='__main__')
"""
    result = subprocess.run(
        [sys.executable, '-c', bootstrap, str(ROOT / 'scripts/check_routing_inputs.py'),
         '--project-root', str(project), '--json'],
        capture_output=True, text=True, check=False, timeout=30,
        env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
    )
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report['status'] == 'blocked' and report['gtfs']['status'] == 'missing'
    assert report['service_date'] == '2026-10-13'
    assert report['timezone'] == 'Australia/Melbourne'
    assert report['project_files_written'] == report['journeys_computed'] == 0
    assert tree_contents(project) == before


def test_cli_invalid_config_returns_exit_one(project):
    config = json.loads((project / PILOT_PATH).read_text())
    config['timezone'] = 'UTC'
    write_json(project / PILOT_PATH, config)
    before = tree_contents(project)
    result = run_cli(project)
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report['status'] == 'invalid' and report['error']
    assert tree_contents(project) == before
