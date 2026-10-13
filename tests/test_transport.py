"""Synthetic tests only: no private files, real GTFS download or notebook execution."""
from __future__ import annotations

import copy
import io
import json
from datetime import date, datetime
from pathlib import Path
from zipfile import ZipFile

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point, Polygon, box, LineString

from homereach.transport import gtfs, spatial, service, pipeline


@pytest.fixture
def calendar():
    return pd.DataFrame([{'service_id':'regular',**{d:'1' for d in gtfs.DAYS},
                          'start_date':'20261001','end_date':'20261031'}]).astype('string')


@pytest.fixture
def exceptions():
    return pd.DataFrame([{'service_id':'regular','date':'20261013','exception_type':'2'},
                         {'service_id':'special','date':'20261013','exception_type':'1'}]).astype('string')


@pytest.mark.parametrize('day,expected',[(1,{'regular'}),(13,{'special'}),(14,{'regular'}),(31,{'regular'})])
def test_calendar_date_selection(calendar,exceptions,day,expected):
    assert gtfs.active_service_ids(calendar,exceptions,date(2026,10,day))==expected


@pytest.mark.parametrize('value',[date(2026,9,30),date(2026,11,1)])
def test_calendar_outside_range(calendar,exceptions,value):
    assert gtfs.active_service_ids(calendar,exceptions,value)==set()


def test_calendar_exception_only(exceptions):
    assert gtfs.active_service_ids(None,exceptions,date(2026,10,13))=={'special'}


def test_calendar_weekday_flag(calendar):
    calendar['tuesday']='0'
    assert gtfs.active_service_ids(calendar,None,date(2026,10,13))==set()


def test_calendar_no_sources():
    assert gtfs.active_service_ids(None,None,date(2026,10,13))==set()


@pytest.mark.parametrize('column,value', [('start_date','20260230'),('end_date','20260901'),
    ('start_date','2026-10-01'),('service_id',' bad'),('service_id',''),('tuesday','2')])
def test_calendar_rejects_invalid_fields(calendar,column,value):
    calendar.loc[0,column]=value
    with pytest.raises(ValueError):gtfs.active_service_ids(calendar,None,date(2026,10,13))


def test_calendar_rejects_duplicate(calendar):
    with pytest.raises(ValueError,match='duplicate'):
        gtfs.active_service_ids(pd.concat([calendar,calendar]),None,date(2026,10,13))


@pytest.mark.parametrize('column,value',[('date','20261301'),('exception_type','3'),('service_id','')])
def test_exception_rejects_bad_fields(calendar,exceptions,column,value):
    exceptions.loc[0,column]=value
    with pytest.raises(ValueError):gtfs.active_service_ids(calendar,exceptions,date(2026,10,13))


def test_conflicting_exception_rejected(calendar,exceptions):
    other=exceptions.iloc[[0]].copy();other['exception_type']='1'
    with pytest.raises(ValueError,match='duplicate'):
        gtfs.active_service_ids(calendar,pd.concat([exceptions,other]),date(2026,10,13))


def test_service_date_must_be_date(calendar):
    with pytest.raises(ValueError):gtfs.active_service_ids(calendar,None,datetime(2026,10,13))


@pytest.mark.parametrize('text,seconds',[('00:00:00',0),('7:00:00',25200),('23:59:59',86399),
    ('24:00:00',86400),('25:15:30',90930),('99:00:00',356400)])
def test_gtfs_time_values(text,seconds):
    assert service.seconds_from_gtfs(pd.Series([text])).iloc[0]==seconds


@pytest.mark.parametrize('text',['','07:60:00','07:00:60','-1:00:00','7:0:00','100:00:00',None,'garbage'])
def test_gtfs_time_rejects_invalid(text):
    with pytest.raises(ValueError):service.seconds_from_gtfs(pd.Series([text]))


@pytest.mark.parametrize('seconds,included',[(25199,False),(25200,True),(32399,True),(32400,False),(111600,False)])
def test_morning_window_edges(seconds,included):
    assert bool(service.in_window(pd.DataFrame({'departure_seconds':[seconds]}),'am_peak_0700_0900').iloc[0]) is included


def test_service_day_retains_extended_time():
    assert service.in_window(pd.DataFrame({'departure_seconds':[111600]}),'service_day').all()


def test_unknown_window_rejected():
    with pytest.raises(ValueError):service.in_window(pd.DataFrame({'departure_seconds':[0]}),'unknown')


@pytest.fixture
def areas():
    return gpd.GeoDataFrame({spatial.CODE:['20001','20002'],spatial.NAME:['Area A','Area B']},
                            geometry=[box(0,0,100,100),box(100,0,200,100)],crs=7855)


def points(geometries,feeds=None,ids=None):
    n=len(geometries);feeds=feeds or ['4']*n;ids=ids or list(map(str,range(n)))
    return gpd.GeoDataFrame({'feed_id':feeds,'stop_id':ids,'stop_key':[f'{f}:{s}' for f,s in zip(feeds,ids)]},
                            geometry=geometries,crs=7855)


@pytest.mark.parametrize('point,status,code',[(Point(50,50),'matched_within','20001'),
    (Point(250,50),'outside_selected_lgas',None),(Point(0,50),'boundary_review',None),
    (Point(100,50),'ambiguous_review',None),(None,'invalid_coordinates',None)])
def test_spatial_status(areas,point,status,code):
    p=points([point]);r,_=spatial.assign_points(p,areas)
    assert r.spatial_match_status.iloc[0]==status
    assert r[spatial.CODE].iloc[0]==code if code else pd.isna(r[spatial.CODE].iloc[0])
    spatial.verify_assignments(r,p,areas)


def test_spatial_overlap_never_forced(areas):
    areas.loc[1,'geometry']=box(25,0,125,100)
    r,_=spatial.assign_points(points([Point(50,50)]),areas)
    assert r.spatial_match_status.iloc[0]=='ambiguous_review'
    assert pd.isna(r[spatial.CODE].iloc[0])


def test_spatial_feed_namespace(areas):
    p=points([Point(50,50),Point(150,50)],['2','3'],['same','same'])
    r,_=spatial.assign_points(p,areas)
    assert r[spatial.CODE].tolist()==['20001','20002']


def test_spatial_duplicate_rejected(areas):
    p=points([Point(50,50)]);p=pd.concat([p,p],ignore_index=True)
    with pytest.raises(ValueError,match='Duplicate'):spatial.assign_points(p,areas)


def test_spatial_swapped_assignment_detected(areas):
    p=points([Point(50,50)]);r,_=spatial.assign_points(p,areas)
    r.loc[0,spatial.CODE]='20002';r.loc[0,spatial.NAME]='Area B'
    with pytest.raises(ValueError):spatial.verify_assignments(r,p,areas)


def test_spatial_shuffling_preserves_matches(areas):
    p=points([Point(50,50),Point(150,50),Point(250,50)])
    a,_=spatial.assign_points(p,areas);b,_=spatial.assign_points(p.iloc[::-1],areas)
    assert a.set_index('stop_key')[spatial.CODE].fillna('').to_dict()==b.set_index('stop_key')[spatial.CODE].fillna('').to_dict()


@pytest.mark.parametrize('fault',['duplicate','empty','invalid','line','crs'])
def test_bad_geographic_input_rejected(areas,fault):
    p=points([Point(50,50)])
    if fault=='duplicate':areas[spatial.CODE]=['20001','20001']
    elif fault=='empty':areas.loc[0,'geometry']=Polygon()
    elif fault=='invalid':areas.loc[0,'geometry']=Polygon([(0,0),(100,100),(0,100),(100,0),(0,0)])
    elif fault=='line':areas.loc[0,'geometry']=LineString([(0,0),(10,10)])
    else:p=p.set_crs(4326,allow_override=True)
    with pytest.raises(ValueError):spatial.assign_points(p,areas)


def test_near_boundary_does_not_assign_outside(areas):
    p=points([Point(5,50),Point(20,50),Point(-5,50),Point(-20,50)])
    assert spatial.mark_near_boundaries(p,areas,10).tolist()==[True,False,True,False]
    r,_=spatial.assign_points(p,areas)
    assert r.spatial_match_status.iloc[2]=='outside_selected_lgas'


@pytest.mark.parametrize('radius',[0,-1,np.nan,np.inf])
def test_bad_diagnostic_radius_rejected(areas,radius):
    with pytest.raises(ValueError):spatial.mark_near_boundaries(points([Point(1,1)]),areas,radius)


def test_boundary_distance_rejects_degrees(areas):
    with pytest.raises(ValueError):spatial.mark_near_boundaries(points([Point(1,1)]).set_crs(4326,allow_override=True),areas.set_crs(4326,allow_override=True))


@pytest.fixture
def locations():
    return pd.DataFrame({'stop_id':['station','platform','bad_coord'],'stop_name':['S','P','X'],
        'stop_lat':['-37.8','-37.8','95'],'stop_lon':['145','145','145'],'location_type':['1','','0'],
        'parent_station':['','station',''],'wheelchair_boarding':['1','0','0']}).astype('string')


def test_location_hierarchy_unknowns_and_invalid_coordinates(locations):
    all_,selected,excluded=spatial.prepare_locations({'2':locations},{'2':'Example'})
    assert len(all_)==3 and len(excluded)==1
    assert selected.stop_id.tolist()==['platform','bad_coord']
    assert selected.parent_key.tolist()==['2:station','']
    assert selected.wheelchair_boarding.tolist()==['0','0']
    assert selected.coordinate_valid.tolist()==[True,False]
    pd.testing.assert_frame_equal(all_[locations.columns],locations)


@pytest.mark.parametrize('column,value',[('stop_id','station'),('stop_id',' bad '),('parent_station','missing'),('location_type','8')])
def test_location_input_rejected(locations,column,value):
    locations.loc[1,column]=value
    with pytest.raises(ValueError):spatial.prepare_locations({'2':locations},{'2':'Example'})


@pytest.fixture
def events_fixture():
    rows=[('T','A','1','07:00:00','0'),('T','A','3','07:30:00',''),('T','B','8','09:00:00','0'),
          ('T','C','10','25:00:00','0'),('N','A','1','08:00:00','1'),('N','C','2','08:20:00','0'),
          ('R','A','0','08:10:00','3'),('R','C','4','08:30:00','0')]
    raw=pd.DataFrame(rows,columns=['trip_id','stop_id','stop_sequence','departure_time','pickup_type'])
    raw['arrival_time']=raw.departure_time;raw['drop_off_type']='0';raw['feed_id']='4';raw['source_line_number']=np.arange(len(raw))+2
    trips=pd.DataFrame({'feed_id':['4']*3,'trip_id':['T','N','R'],'trip_key':['4:T','4:N','4:R'],
        'route_id':['R1']*3,'route_key':['4:R1']*3,'service_category':['myki_bus']*3,'is_labelled_replacement_bus':[False]*3})
    lookup=pd.DataFrame({'feed_id':['4']*3,'stop_id':['A','B','C'],'stop_key':['4:A','4:B','4:C'],
        'stop_name':['Alpha','Beta','Outside'],'lga_code_2025':['20001','20002',''],'abs_lga_name':['Area A','Area B',''],
        'spatial_match_status':['matched_within','matched_within','outside_selected_lgas'],'near_boundary_10m':[False,True,False]})
    return raw,trips,lookup


def test_terminal_uses_complete_trip(events_fixture):
    raw,trips,lookup=events_fixture;events=service.classify_active_events(raw,trips,lookup)
    assert events.loc[events.trip_id.eq('T') & events.stop_id.eq('B'),'has_onward_stop'].all()
    assert (events.selection_outcome=='counted_regular_pickup').sum()==3
    assert events.loc[events.trip_id.eq('T') & events.stop_id.eq('C'),'selection_outcome'].iloc[0]=='terminal_trip_record'


@pytest.mark.parametrize('pickup,outcome',[('','counted_regular_pickup'),('0','counted_regular_pickup'),('1','no_pickup'),('2','arrangement_required'),('3','arrangement_required')])
def test_pickup_rules(events_fixture,pickup,outcome):
    raw,trips,lookup=events_fixture;raw.loc[0,'pickup_type']=pickup
    assert service.classify_active_events(raw,trips,lookup).selection_outcome.iloc[0]==outcome


def test_terminal_outcome_precedes_other_exclusions(events_fixture):
    raw,trips,lookup=events_fixture;raw.loc[3,'pickup_type']='1'
    result=service.classify_active_events(raw,trips,lookup)
    assert result.selection_outcome.iloc[3]=='terminal_trip_record'


def test_outside_eligible_visit_is_retained_unassigned(events_fixture):
    raw,trips,lookup=events_fixture;raw.loc[0,'stop_id']='C'
    result=service.classify_active_events(raw,trips,lookup)
    assert result.selection_outcome.iloc[0]=='unassigned_location'


def test_events_are_not_trips_and_cross_lga_trips_not_additive(events_fixture):
    summaries=service.summarize_events(service.classify_active_events(*events_fixture))
    net=summaries['network'].query("window=='service_day'").iloc[0]
    assert net.eligible_departure_events==3 and net.unique_trip_records==1
    assert summaries['lga'].query("window=='service_day'").unique_trip_records.sum()==2
    am=summaries['network'].query("window=='am_peak_0700_0900'").iloc[0]
    assert am.eligible_departure_events==2 and am.unique_trip_records==1


def test_event_row_order_independent(events_fixture):
    raw,trips,lookup=events_fixture
    a=service.classify_active_events(raw,trips,lookup);b=service.classify_active_events(raw.sample(frac=1,random_state=7),trips,lookup)
    cols=service.EVENT_KEYS+['selection_outcome','trip_last_sequence']
    pd.testing.assert_frame_equal(a[cols].sort_values(service.EVENT_KEYS).reset_index(drop=True),b[cols].sort_values(service.EVENT_KEYS).reset_index(drop=True))


@pytest.mark.parametrize('field,value',[('stop_sequence','-1'),('stop_sequence','1.5'),('departure_time','07:60:00'),('arrival_time','08:30:00'),('pickup_type','4'),('drop_off_type','9'),('stop_id','')])
def test_malformed_event_rejected(events_fixture,field,value):
    raw,trips,lookup=events_fixture;raw.loc[0,field]=value
    with pytest.raises(ValueError):service.classify_active_events(raw,trips,lookup)


def test_numeric_duplicate_sequence_rejected(events_fixture):
    raw,trips,lookup=events_fixture;extra=raw.iloc[[0]].copy();extra['stop_sequence']='01'
    with pytest.raises(ValueError,match='Duplicate event key'):
        service.classify_active_events(pd.concat([raw,extra]),trips,lookup)


def test_missing_active_trip_rejected(events_fixture):
    raw,trips,lookup=events_fixture
    with pytest.raises(ValueError,match='Missing or unexpected'):
        service.classify_active_events(raw.loc[raw.trip_id.ne('T')],trips,lookup)


def test_unknown_stop_is_not_outside(events_fixture):
    raw,trips,lookup=events_fixture
    with pytest.raises(ValueError,match='Missing or ambiguous'):
        service.classify_active_events(raw,trips,lookup.loc[lookup.stop_id.ne('C')])


def test_other_feed_stop_does_not_change_assignment(events_fixture):
    raw,trips,lookup=events_fixture;other=lookup.copy();other['feed_id']='3';other['stop_key']='3:'+other.stop_id;other['lga_code_2025']='29999'
    events=service.classify_active_events(raw,trips,pd.concat([lookup,other],ignore_index=True))
    assert events.loc[events.stop_id.eq('A'),'lga_code_2025'].eq('20001').all()


def test_replacement_categories_separate():
    data=pd.DataFrame({'feed_id':['2','2','3','4'],'trip_id':['a','b','c','d'],'is_labelled_replacement_bus':[False,True,False,False]})
    assert service.categorize_trips(data).service_category.tolist()==list(service.CATEGORY_FEED)


def test_unreviewed_replacement_feed_rejected():
    data=pd.DataFrame({'feed_id':['3'],'trip_id':['a'],'is_labelled_replacement_bus':[True]})
    with pytest.raises(ValueError):service.categorize_trips(data)


def write_nested(path,tables,feed='4',extra=None):
    stream=io.BytesIO()
    with ZipFile(stream,'w') as inner:
        for name,table in tables.items():inner.writestr(name,table.to_csv(index=False))
        for name,content in (extra or {}).items():inner.writestr(name,content)
    with ZipFile(path,'w') as outer:outer.writestr(f'{feed}/google_transit.zip',stream.getvalue())


@pytest.mark.parametrize('chunk_rows',[1,3,100])
def test_chunk_scan_invariant_and_zero_grid(events_fixture,tmp_path,chunk_rows):
    raw,trips,lookup=events_fixture;path=tmp_path/'gtfs.zip'
    write_nested(path,{'stop_times.txt':raw[service.RAW_EVENT_COLUMNS]})
    result=service.scan_service_feed(path,'4',trips,lookup,len(raw),chunk_rows)
    lgas=pd.DataFrame({'lga_code_2025':['20001','20002','20003'],'abs_lga_name':['Area A','Area B','Zero Area'],'rental_area_name':['A','B','Z']}).astype('string')
    tables=service.combine_service_results({'4':result},trips,lgas,date(2026,10,13),len(raw))
    assert len(tables['lga_service_indicators.csv'])==3*4*2
    assert tables['lga_service_indicators.csv'].query("lga_code_2025=='20003'").eligible_departure_events.sum()==0
    trace=tables['event_trace_examples.csv']
    assert trace.loc[trace.trip_id.eq('T') & trace.stop_sequence.eq(1),'source_line_number'].eq(2).all()


def test_duplicate_spanning_chunks_rejected(events_fixture,tmp_path):
    raw,trips,lookup=events_fixture;raw=pd.concat([raw,raw.iloc[[0]]]);path=tmp_path/'gtfs.zip'
    write_nested(path,{'stop_times.txt':raw[service.RAW_EVENT_COLUMNS]})
    with pytest.raises(ValueError,match='Duplicate event key'):service.scan_service_feed(path,'4',trips,lookup,len(raw),2)


@pytest.mark.parametrize('unsupported',['frequencies.txt','continuous_pickup','location_group_id'])
def test_unsupported_feed_features_rejected(events_fixture,tmp_path,unsupported):
    raw,trips,lookup=events_fixture;data=raw[service.RAW_EVENT_COLUMNS].copy();extra={}
    if unsupported.endswith('.txt'):extra[unsupported]='trip_id,start_time,end_time,headway_secs\n'
    else:data[unsupported]=''
    path=tmp_path/'gtfs.zip';write_nested(path,{'stop_times.txt':data},extra=extra)
    with pytest.raises(ValueError):service.scan_service_feed(path,'4',trips,lookup,len(raw),2)


def test_missing_feed_member_rejected(tmp_path):
    path=tmp_path/'a.zip'
    with ZipFile(path,'w'):pass
    with pytest.raises(ValueError):
        with gtfs.open_feed(path,'4'):pass


def test_csv_mismatch_does_not_overwrite(tmp_path):
    path=tmp_path/'table.csv';path.write_text('a,b\nwrong,2\n')
    before=path.read_bytes()
    with pytest.raises(ValueError):pipeline.check_csv(path,pd.DataFrame({'a':['right'],'b':[2]}))
    assert path.read_bytes()==before


def test_csv_preserves_ids_and_missing_text(tmp_path):
    data=pd.DataFrame({'id':['001','NA','None',''],'count':[1,2,3,4]}).astype({'id':'string'})
    path=tmp_path/'table.csv';data.to_csv(path,index=False)
    pipeline.check_csv(path,data)


@pytest.fixture
def mini_outputs():
    sample=pd.DataFrame({'id':['001'],'value':[2]})
    sp={n:sample.copy() for n in pipeline.SPATIAL_NAMES};sv={n:sample.copy() for n in pipeline.SERVICE_NAMES}
    points_=gpd.GeoDataFrame({'stop_key':pd.Series(['4:001'],dtype='string'),'x':pd.Series([''],dtype='string'),'flag':[True],'n':[2],'latitude':[-37.8]},geometry=[Point(145,-37.8)],crs=4326)
    sp['stop_lga_matches.csv']=pd.DataFrame(points_.drop(columns='geometry'))
    return sp,sv,points_


def test_export_roundtrip_checkonly_and_no_clobber(tmp_path,mini_outputs):
    sp,sv,p=mini_outputs;input_=tmp_path/'source.txt';input_.write_text('unchanged')
    hashes={input_:gtfs.sha256_file(input_)}
    check=pipeline.export_outputs(tmp_path,sp,p,sv,{},hashes,check_only=True)
    assert check['project_output_files_written']==0 and not (tmp_path/'data/processed').exists()
    report=pipeline.export_outputs(tmp_path,sp,p,sv,{},hashes,check_only=False)
    assert report['csv_readback_matches'] is True and report['gpkg_readback_matches'] is True
    assert len(report['output_sha256'])==18
    dest=tmp_path/'data/processed/transport/service/lga_service_indicators.csv';before=dest.read_bytes()
    changed={**sv,'lga_service_indicators.csv':pd.DataFrame({'id':['001'],'value':[999]})}
    with pytest.raises(ValueError):pipeline.export_outputs(tmp_path,sp,p,changed,{},hashes,check_only=False)
    assert dest.read_bytes()==before
    check=pipeline.export_outputs(tmp_path,sp,p,sv,{},hashes,check_only=True)
    assert len(check['previous_pipeline_exports_compared'])==18


def test_upstream_change_aborts_export(tmp_path,mini_outputs):
    sp,sv,p=mini_outputs;src=tmp_path/'src';src.write_text('before');hashes={src:gtfs.sha256_file(src)};src.write_text('after')
    with pytest.raises(ValueError):pipeline.export_outputs(tmp_path,sp,p,sv,{},hashes,check_only=False)
    assert not (tmp_path/'data/processed/transport').exists()


def test_gpkg_changed_point_is_rejected(tmp_path):
    expected=gpd.GeoDataFrame({'stop_key':pd.Series(['4:A'],dtype='string'),'id':pd.Series(['001'],dtype='string')},geometry=[Point(145,-37.8)],crs=4326)
    bad=expected.copy();bad.loc[0,'geometry']=Point(146,-37.8);path=tmp_path/'p.gpkg'
    bad.to_file(path,layer='stop_lga_matches',driver='GPKG',engine='pyogrio')
    with pytest.raises(ValueError,match='coordinates'):pipeline.check_points(path,expected)


def test_registry_update_preserves_other_records_and_notes(tmp_path):
    path=tmp_path/'r.csv';path.write_text('dataset_id,status,notes\nrent,validated,keep rent\ngtfs,not_downloaded,keep my note\nheat,pending,unchanged\n')
    spec={'filename':'gtfs.zip','sha256':'a'*64,'service_date':'2026-10-13','timezone':'Australia/Melbourne'}
    text=pipeline.registry_update_text(path,spec);data=pd.read_csv(io.StringIO(text),keep_default_na=False)
    assert data.loc[data.dataset_id.eq('rent'),'status'].iloc[0]=='validated'
    assert data.loc[data.dataset_id.eq('gtfs'),'notes'].iloc[0]=='keep my note'
    assert data.loc[data.dataset_id.eq('gtfs'),'status'].iloc[0]=='service_indicators_validated'
    assert 'download_date' not in data.columns
    assert 'not_downloaded' in path.read_text()


@pytest.mark.parametrize('text',['dataset_id,status\nrent,ok\n','dataset_id,status\ngtfs,a\ngtfs,b\n','dataset_id,status\ngtfs\n','dataset_id,status,status\ngtfs,a,a\n'])
def test_invalid_registry_rejected(tmp_path,text):
    path=tmp_path/'r.csv';path.write_text(text)
    with pytest.raises(ValueError):pipeline.registry_update_text(path,{})


def test_registry_backup_and_concurrent_edit_guard(tmp_path):
    path=tmp_path/'docs/data_registry.csv';path.parent.mkdir();path.write_text('dataset_id,status\ngtfs,old\n')
    old=path.read_bytes();h=gtfs.sha256_file(path)
    new='dataset_id,status\ngtfs,new\n';pipeline.save_registry(tmp_path,new,h)
    assert path.read_text()==new
    assert list((tmp_path/'data/interim/registry_backups').glob('*.csv'))[0].read_bytes()==old
    with pytest.raises(ValueError):pipeline.save_registry(tmp_path,'changed',h)


def test_reviewed_config_loads():
    path=Path(__file__).resolve().parents[1]/'config/gtfs_snapshot.json'
    assert pipeline.load_transport_snapshot(path)['service_date']=='2026-10-13'


@pytest.mark.parametrize('field,value',[('service_date','2026-10-14'),('sha256','0'*64),('near_boundary_metres',20),('feed_ids',['2','3']),('match_epsg',4326)])
def test_config_changes_require_review(tmp_path,field,value):
    source=Path(__file__).resolve().parents[1]/'config/gtfs_snapshot.json';spec=json.loads(source.read_text());spec[field]=value
    target=tmp_path/'s.json';target.write_text(json.dumps(spec))
    with pytest.raises(ValueError,match='Re-audit'):pipeline.load_transport_snapshot(target)
