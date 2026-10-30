"""Portable-release checks use fictional 31-area data; no government files/network."""
from pathlib import Path
from copy import deepcopy
import json
import shutil
import subprocess
import sys
import hashlib
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon, mapping
from homereach.explorer.analysis import CODE, AM_WINDOW, DAY_WINDOW, RENT_QUARTER, SERVICE_DATE, CATEGORY_LABELS, fingerprint
from homereach.explorer.bundle import TABLE_NAMES, GEOJSON, MANIFEST, REPORTS, table_schema, bundle_signature
from homereach.explorer.release import (DATA_NAMES, PAYLOAD_NAMES, RELEASE_NAMES, ATTRIBUTIONS, ATTRIBUTION_FILE,
    RELEASE_MANIFEST, canonical_json, content_id, load_release, release_signature, package_release, validate_release_tables)


def fake_tables():
    """Hard-coded audited dimensions with deliberately FICTIONAL names/values."""
    codes=[str(20001+i) for i in range(31)]
    counts=[5000]*30+[8932]
    areas=pd.DataFrame({CODE:codes, 'rental_area_name':[f'Fixture {i:02}' for i in range(31)],
        'abs_lga_name':[f'Fixture {i:02}' for i in range(31)], 'source_region':['Fixture region']*31,
        'quarter':[RENT_QUARTER]*31, 'property_type':['2 bedroom flats']*31,
        'transport_service_date':[SERVICE_DATE]*31, 'median_weekly_rent':[500.]*31,
        'published_count':[10]*31, 'am_departure_events':counts, 'am_unique_trip_records':[10]*31,
        'am_served_stop_records':[1]*31, 'assigned_stop_records':[2]*31,
        'assigned_records_without_counted_am_event':[1]*31,
        'mean_am_events_per_assigned_stop_record':[n/2 for n in counts],
        'mean_am_events_per_served_stop_record':[float(n) for n in counts],
        'transport_timezone':['Australia/Melbourne']*31, 'source_file':['fixture.xlsx']*31,
        'source_sheet':['Fixture']*31,'source_count_cell':['C4']*31,'source_median_cell':['D4']*31})
    history=[]
    for r in areas.to_dict('records'):
        for q in pd.period_range('1999Q2',RENT_QUARTER,freq='Q'):
            history.append({k:r[k] for k in [CODE,'rental_area_name','property_type','published_count','median_weekly_rent','source_count_cell','source_median_cell']}
                           | {'quarter':str(q),'quarter_end':q.end_time.normalize()})
    cats=[]
    for i,code in enumerate(codes):
        for window in [AM_WINDOW,DAY_WINDOW]:
            for cat in CATEGORY_LABELS:
                n=counts[i] if cat=='tram' else 0
                cats.append({CODE:code,'window':window,'service_category':cat,'eligible_departure_events':n,
                             'unique_trip_records':int(n>0)*10,'served_stop_records':int(n>0),'unique_route_records':int(n>0)})
    tables={name:pd.DataFrame({'fixture':['fixture']}) for name in TABLE_NAMES}
    tables.update({'rent_transport_comparison.csv':areas,'rental_history.csv':pd.DataFrame(history),
       'lga_service_categories.csv':pd.DataFrame(cats),
       'study_area_reconciliation.csv':pd.DataFrame([{'window':AM_WINDOW,'distinct_study_area_trips':5768,
        'sum_of_lga_trip_counts_not_a_study_area_total':12546}]),
       'source_periods.csv':pd.DataFrame({'component':['rent','transport','boundaries'],'period':[RENT_QUARTER,SERVICE_DATE,'2025'],
         'scope':['fictional test data']*3,'publisher_page':['https://example.org']*3,'source_file':['fixture']*3,'source_sha256':['0'*64]*3})})
    return tables


@pytest.fixture
def local_bundle(tmp_path):
    root=tmp_path/'project';folder=root/'data/processed/explorer';folder.mkdir(parents=True)
    tables=fake_tables()
    for name,t in tables.items():t.to_csv(folder/name,index=False,date_format='%Y-%m-%d',lineterminator='\n')
    features=[]
    for i,row in tables['rent_transport_comparison.csv'].iterrows():
        x=144.0+i*.02;y=-38.0
        features.append({'type':'Feature','id':row[CODE], 'properties':{CODE:row[CODE],'abs_lga_name':row.abs_lga_name},
          'geometry':mapping(Polygon([(x,y),(x+.01,y),(x+.01,y+.01),(x,y+.01)]))})
    (folder/GEOJSON).write_bytes(canonical_json({'type':'FeatureCollection','features':features}))
    for rel in REPORTS:
        p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{"fixture":true}\n')
    m={'schema_version':1,'builder':'scripts/build_explorer_data.py','check_only':False,
       'created_at_utc':'2026-10-26T00:00:00+00:00',
       'scope':{'rental_quarter':RENT_QUARTER,'transport_service_date':SERVICE_DATE,'timezone':'Australia/Melbourne',
        'property_type':'2 bedroom flats','boundary_year':2025,'lga_count':31,'selected_feeds':['2','3','4'],'score_or_prediction':False},
       'quality':{'joined_lgas':31,'unmatched_lgas':0,'duplicate_codes':0,'rental_history_rows':3286,'service_category_rows':248,
        'am_events':158932,'distinct_study_area_am_trips':5768,'rental_fields_preserved':14,'input_files_unchanged':True,
        'geometry_features':31,'raw_gtfs_scans':0},
       'output_sha256':{n:fingerprint(folder/n) for n in DATA_NAMES},
       'output_schemas':{n:table_schema(t) for n,t in tables.items()},
       'upstream_report_sha256':{rel:fingerprint(root/rel) for rel in REPORTS},
       'notebook_tables_compared':[],'csv_readback_matches':True,'geojson_readback_matches':True,
       'private_test_field':'C:\\Users\\private-test-only\\secret'}
    (folder/MANIFEST).write_bytes(canonical_json(m))
    return root


@pytest.fixture
def release_dir(local_bundle):
    package_release(local_bundle)
    return local_bundle/'deploy/data'


def snapshots(root):return {str(p.relative_to(root)):fingerprint(p) for p in root.rglob('*') if p.is_file()}


def edit_manifest(folder, update):
    p=folder/RELEASE_MANIFEST;m=json.loads(p.read_text());update(m);p.write_bytes(canonical_json(m))


def test_check_only_has_no_writes(local_bundle):
    before=snapshots(local_bundle)
    result=package_release(local_bundle,check_only=True)
    assert result['output_files_written']==0 and snapshots(local_bundle)==before
    assert not (local_bundle/'deploy').exists()


def test_export_and_all_source_bytes_preserved(local_bundle):
    before=snapshots(local_bundle/'data')
    result=package_release(local_bundle)
    release=local_bundle/'deploy/data'
    assert result['output_files_written']==11
    assert set(p.name for p in release.iterdir())==set(RELEASE_NAMES)
    assert snapshots(local_bundle/'data')==before
    for name in DATA_NAMES:assert (release/name).read_bytes()==(local_bundle/'data/processed/explorer'/name).read_bytes()


def test_no_live_upstream_required(release_dir,tmp_path):
    isolated=tmp_path/'isolated'/'data';shutil.copytree(release_dir,isolated)
    shutil.rmtree(release_dir.parents[1]/'data')
    b=load_release(isolated)
    assert len(b.areas)==31 and len(b.tables['rental_history.csv'])==3286


def test_repeat_package_is_byte_stable(local_bundle):
    package_release(local_bundle);before=snapshots(local_bundle)
    result=package_release(local_bundle)
    assert result['output_files_written']==0 and result['existing_identical']
    assert snapshots(local_bundle)==before


def test_private_build_metadata_not_published(release_dir):
    m=json.loads((release_dir/RELEASE_MANIFEST).read_text())
    assert 'private_test_field' not in m and 'upstream_report_sha256' not in m and 'input_sha256' not in m
    assert 'C:\\Users' not in (release_dir/RELEASE_MANIFEST).read_text()
    assert 'source_bundle_manifest_sha256' in m


@pytest.mark.parametrize('name',DATA_NAMES)
def test_every_payload_byte_change_rejected(release_dir,name):
    with (release_dir/name).open('ab') as f:f.write(b' ')
    with pytest.raises(ValueError,match='changed'):load_release(release_dir)


@pytest.mark.parametrize('name',['.env','secrets.toml','extra.csv','gtfs.zip'])
def test_unapproved_file_rejected(release_dir,name):
    (release_dir/name).write_text('unexpected')
    with pytest.raises(ValueError,match='inventory'):release_signature(release_dir)


def test_missing_payload_rejected(release_dir):
    (release_dir/TABLE_NAMES[0]).unlink()
    with pytest.raises(ValueError,match='inventory'):load_release(release_dir)


def test_payload_symlink_rejected(release_dir,monkeypatch):
    # No Windows symlink privileges are needed to exercise the rejection guard.
    target=release_dir/TABLE_NAMES[0]
    original=Path.is_symlink
    monkeypatch.setattr(Path,'is_symlink',lambda p: p==target or original(p))
    with pytest.raises(ValueError,match='symlink'):release_signature(release_dir)


def test_path_traversal_manifest_entry_rejected(release_dir):
    edit_manifest(release_dir,lambda m:m['output_sha256'].update({'../../secrets.toml':'0'*64}))
    with pytest.raises(ValueError,match='allowlist'):release_signature(release_dir)


@pytest.mark.parametrize('field,value',[('check_only',True),('self_contained',False),('release_schema_version',2),('builder','other.py'),('csv_readback_matches',False)])
def test_wrong_release_kind_rejected(release_dir,field,value):
    edit_manifest(release_dir,lambda m:m.update({field:value}))
    with pytest.raises(ValueError):release_signature(release_dir)


@pytest.mark.parametrize('field,value',[('rental_quarter','2026Q1'),('transport_service_date','2026-10-14'),('score_or_prediction',True)])
def test_scope_changes_rejected(release_dir,field,value):
    edit_manifest(release_dir,lambda m:m['scope'].update({field:value}))
    with pytest.raises(ValueError,match='scope'):load_release(release_dir)


def test_attribution_tampering_even_with_new_hash_rejected(release_dir):
    path=release_dir/ATTRIBUTION_FILE;a=json.loads(path.read_text());a['sources'][0]['licence']='Made up';path.write_bytes(canonical_json(a))
    def change(m):
        m['output_sha256'][ATTRIBUTION_FILE]=fingerprint(path);m['release_id']=content_id(m['output_sha256'])
    edit_manifest(release_dir,change)
    with pytest.raises(ValueError,match='attribution'):load_release(release_dir)


def test_unknown_release_metadata_rejected(release_dir):
    edit_manifest(release_dir,lambda m:m.update({'local_path':'C:/Users/example'}))
    with pytest.raises(ValueError,match='unknown fields'):load_release(release_dir)


def test_cached_signature_mismatch_rejected(release_dir):
    with pytest.raises(ValueError,match='changed'):load_release(release_dir,expected_signature='old')


def test_local_loader_stays_strict(local_bundle):
    package_release(local_bundle)
    (local_bundle/REPORTS[0]).write_text('changed')
    with pytest.raises(ValueError,match='Upstream'):bundle_signature(local_bundle)
    with pytest.raises(ValueError,match='Upstream'):package_release(local_bundle)
    assert len(load_release(local_bundle/'deploy/data').areas)==31


@pytest.mark.parametrize('problem',['date','history_value','duplicate_category','sum','record_id','period'])
def test_semantic_corruption_rejected(problem):
    t=fake_tables()
    if problem=='date':t['rental_history.csv'].loc[0,'quarter_end']+=pd.Timedelta(days=1)
    elif problem=='history_value':t['rental_history.csv'].loc[105,'median_weekly_rent']=501.
    elif problem=='duplicate_category':t['lga_service_categories.csv'].iloc[1]=t['lga_service_categories.csv'].iloc[0]
    elif problem=='sum':t['lga_service_categories.csv'].loc[2,'eligible_departure_events']+=1
    elif problem=='record_id':t[TABLE_NAMES[0]]['trip_id']='private'
    else:t['source_periods.csv'].loc[0,'period']='2026Q1'
    with pytest.raises(ValueError):validate_release_tables(t)


def test_no_build_only_imports_in_release_runtime():
    script="""import builtins
real_import=builtins.__import__
def check(name,*args,**kwargs):
    if name.split('.')[0] in {'geopandas','pyogrio','pyproj','openpyxl','sklearn'}:
        raise RuntimeError('Forbidden build import: '+name)
    return real_import(name,*args,**kwargs)
builtins.__import__=check
from homereach.explorer.release import load_release
print('OK')
"""
    result=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_windows_git_line_endings_preserve_payload(tmp_path):
    git=shutil.which('git')
    if not git:pytest.skip('Git not installed.')
    repo=tmp_path/'git';repo.mkdir();(repo/'deploy/data').mkdir(parents=True)
    project=Path(__file__).resolve().parents[1]
    shutil.copyfile(project/'deploy/.gitattributes',repo/'deploy/.gitattributes')
    payload=b'a,b\n1,2\n';p=repo/'deploy/data/fixture.csv';p.write_bytes(payload)
    def run(*args):return subprocess.run([git,'-C',str(repo),*args],check=True,capture_output=True)
    run('init');run('config','core.autocrlf','true');run('add','deploy')
    assert run('show',':deploy/data/fixture.csv').stdout==payload
