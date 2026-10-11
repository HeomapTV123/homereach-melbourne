"""Offline synthetic tests: no official ZIP/XLSX, live API or user files needed."""
from __future__ import annotations

import csv
import io
import json
from copy import deepcopy
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon, MultiPolygon, Point, box

from homereach.geography import lga
from homereach.io.dffh_rent import COLUMN_ORDER, TEXT_COLUMNS


@pytest.fixture
def example():
    names = ["Fixture A", "Fixture B", "Fixture C short"]
    codes = ["20010", "20020", "20030"]
    official = ["Fixture A", "Fixture B", "Fixture C official"]
    polys = [box(144.7, -37.9, 144.8, -37.8), box(144.8, -37.9, 144.9, -37.8),
             MultiPolygon([box(144.9, -37.9, 145.0, -37.8), box(145.01, -37.9,145.02,-37.89)])]
    councils = gpd.GeoDataFrame({"LGA_CODE25": codes, "LGA_NAME25": official,
        "STE_CODE21": ["2"]*3, "STE_NAME21": ["Victoria"]*3,
        "AUS_CODE21": ["AUS"]*3, "AUS_NAME21": ["Australia"]*3,
        "AREASQKM": [10.0, 20.0, 30.0]}, geometry=polys, crs=7844)
    for col in ["LGA_CODE25", "LGA_NAME25", "STE_CODE21", "STE_NAME21"]:
        councils[col] = councils[col].astype("string")
    aliases = pd.DataFrame([[names[2], codes[2], official[2], "Fictional reviewed expansion"]],
                           columns=lga.ALIAS_COLUMNS).astype("string")
    spec = {"property_type": "2 bedroom flats", "filename": "fixture.xlsx", "sheet": "2br Flat",
            "reporting_quarter": "2025Q3", "first_quarter": "2024Q2", "last_quarter": "2025Q3",
            "metro_group_counts": {"Fixture Metro": 3}}
    periods = pd.period_range("2024Q2", "2025Q3", freq="Q")
    rows = []
    for area_idx, name in enumerate(names):
        for q_idx, q in enumerate(periods):
            rows.append({"rental_area_name": name, "source_region": "Fixture Metro", "area_type": "LGA",
                "property_type": "2 bedroom flats", "quarter": str(q),
                "quarter_end": q.to_timestamp(how="end").normalize(), "published_count": 10 + area_idx,
                "median_weekly_rent": 400.0 + area_idx*30 + q_idx*5,
                "source_file": "fixture.xlsx", "source_sheet": "2br Flat", "source_reporting_quarter": "2025Q3",
                "source_excel_row": 4+area_idx, "source_count_cell": f"C{4+area_idx}", "source_median_cell": f"D{4+area_idx}"})
    panel = pd.DataFrame(rows, columns=COLUMN_ORDER)
    for col in TEXT_COLUMNS:
        panel[col] = panel[col].astype("string")
    panel["published_count"] = panel["published_count"].astype("Int64")
    panel["quarter_end"] = panel["quarter_end"].astype("datetime64[ns]")
    geo_spec = {"mapped_records": 3, "map_quarter": "2025Q3"}
    latest = lga.select_latest(panel, spec, geo_spec)
    native, crosswalk, mapped = lga.join_boundaries(latest, councils, aliases)
    return {"councils": councils, "aliases": aliases, "panel": panel, "latest": latest,
            "rent_spec": spec, "geo_spec": geo_spec, "native": native, "crosswalk": crosswalk, "mapped": mapped}


def test_valid_crosswalk_and_nonmutating_join(example):
    e = example
    before = e["latest"].copy(deep=True)
    native, crosswalk, mapped = lga.join_boundaries(e["latest"], e["councils"], e["aliases"])
    assert crosswalk.match_method.tolist() == ["exact_name", "exact_name", "reviewed_alias"]
    assert crosswalk[lga.CODE].tolist() == ["20010", "20020", "20030"]
    assert native.geom_type.tolist() == ["Polygon", "Polygon", "MultiPolygon"]
    pd.testing.assert_frame_equal(before, e["latest"])
    lga.verify_map(mapped, e["latest"], crosswalk, native)


def test_shuffle_inputs_keeps_same_result(example):
    e = example
    _, c, m = lga.join_boundaries(e["latest"].sample(frac=1, random_state=1),
                                  e["councils"].sample(frac=1, random_state=2), e["aliases"])
    pd.testing.assert_frame_equal(c, e["crosswalk"])
    lga.verify_map(m, e["latest"], c, e["native"])


@pytest.mark.parametrize("problem", ["unknown_name", "duplicate_source", "duplicate_lookup_name", "duplicate_lookup_code",
    "duplicate_alias", "missing_alias", "extra_alias", "wrong_alias_code", "wrong_alias_name", "shared_code", "blank_name", "null_code"])
def test_bad_name_associations_are_rejected(example, problem):
    e=example
    source=e["latest"][["rental_area_name", "source_region"]].copy()
    lookup=e["councils"][["LGA_CODE25", "LGA_NAME25"]].rename(columns=lga.NATIVE_FIELDS).copy()
    aliases=e["aliases"].copy()
    if problem=="unknown_name": source.loc[0,"rental_area_name"]="Unknown"
    elif problem=="duplicate_source": source=pd.concat([source,source.iloc[[0]]],ignore_index=True)
    elif problem=="duplicate_lookup_name": lookup.loc[1,lga.NAME]=lookup.loc[0,lga.NAME]
    elif problem=="duplicate_lookup_code": lookup.loc[1,lga.CODE]=lookup.loc[0,lga.CODE]
    elif problem=="duplicate_alias": aliases=pd.concat([aliases,aliases],ignore_index=True)
    elif problem=="missing_alias": aliases=aliases.iloc[0:0]
    elif problem=="extra_alias":
        extra=aliases.copy(); extra.loc[0,"rental_area_name"]="Unused"; aliases=pd.concat([aliases,extra],ignore_index=True)
    elif problem=="wrong_alias_code": aliases.loc[0,lga.CODE]="29999"
    elif problem=="wrong_alias_name": aliases.loc[0,lga.NAME]="Not the official name"
    elif problem=="shared_code": aliases.loc[0,[lga.CODE,lga.NAME]]=["20010","Fixture A"]
    elif problem=="blank_name": source.loc[0,"rental_area_name"]=""
    elif problem=="null_code": lookup.loc[0,lga.CODE]=pd.NA
    with pytest.raises((ValueError,AssertionError)):
        lga.build_crosswalk(source,lookup,aliases)


@pytest.mark.parametrize("problem", ["null", "empty", "invalid", "point", "swapped_shapes", "swapped_codes", "rent", "count",
    "source_cell", "quarter", "crs", "official_name", "region", "method", "note", "boundary_year", "state", "area", "duplicate_row", "lost_row"])
def test_corrupted_mapped_data_is_rejected(example, problem):
    e=example; frame=e["mapped"].copy(deep=True)
    if problem=="null": frame.at[0,"geometry"]=None
    elif problem=="empty": frame.at[0,"geometry"]=Polygon()
    elif problem=="invalid": frame.at[0,"geometry"]=Polygon([(144,-38),(145,-37),(144,-37),(145,-38),(144,-38)])
    elif problem=="point": frame.at[0,"geometry"]=Point(144.8,-37.8)
    elif problem=="swapped_shapes": frame.loc[[0,1],"geometry"]=frame.loc[[1,0],"geometry"].to_numpy()
    elif problem=="swapped_codes": frame.loc[[0,1],lga.CODE]=frame.loc[[1,0],lga.CODE].to_numpy()
    elif problem=="rent": frame.at[0,"median_weekly_rent"]+=1
    elif problem=="count": frame.at[0,"published_count"]+=1
    elif problem=="source_cell": frame.at[0,"source_median_cell"]="ZZ99"
    elif problem=="quarter": frame.at[0,"quarter"]="2024Q3"
    elif problem=="crs": frame=frame.set_crs(4326,allow_override=True)
    elif problem=="official_name": frame.at[0,lga.NAME]="Other"
    elif problem=="region": frame.at[0,"source_region"]="Other"
    elif problem=="method": frame.at[0,"match_method"]="fuzzy"
    elif problem=="note": frame.at[0,"match_note"]="unreviewed"
    elif problem=="boundary_year": frame.at[0,"boundary_year"]=2026
    elif problem=="state": frame.at[0,"state_code"]="1"
    elif problem=="area": frame.at[0,"abs_area_sqkm"]+=1
    elif problem=="duplicate_row": frame=pd.concat([frame,frame.iloc[[0]]],ignore_index=True)
    elif problem=="lost_row": frame=frame.iloc[1:].copy()
    with pytest.raises((ValueError,AssertionError)):
        lga.verify_map(frame,e["latest"],e["crosswalk"],e["native"])


@pytest.mark.parametrize("unit", ["ns", "us", "ms", "s"])
def test_datetime_resolution_is_not_a_date_error(example, unit):
    e=example; panel=e["panel"].copy()
    panel["quarter_end"]=panel["quarter_end"].dt.as_unit(unit)
    result=lga.select_latest(panel,e["rent_spec"],e["geo_spec"])
    assert len(result)==3


@pytest.mark.parametrize("problem", ["date", "missing_quarter", "duplicate", "category", "count", "zero_rent"])
def test_bad_rental_input_is_rejected(example,problem):
    e=example; panel=e["panel"].copy()
    if problem=="date": panel.at[0,"quarter_end"]+=pd.Timedelta(days=1)
    elif problem=="missing_quarter": panel=panel.iloc[1:]
    elif problem=="duplicate": panel=pd.concat([panel,panel.iloc[[0]]],ignore_index=True)
    elif problem=="category": panel.at[0,"property_type"]="3 bedroom houses"
    elif problem=="count": panel["published_count"]=panel["published_count"].astype(float)+0.5
    elif problem=="zero_rent": panel.at[0,"median_weekly_rent"]=0
    with pytest.raises((ValueError,AssertionError)):
        lga.select_latest(panel,e["rent_spec"],e["geo_spec"])


def test_web_export_does_not_change_native_geometry(example):
    e=example; before=e["native"].copy()
    doc=lga.to_web_geojson(e["mapped"])
    assert len(doc["features"])==3
    assert doc["features"][0]["properties"]["quarter_end"]=="2025-09-30"
    assert [f["id"] for f in doc["features"]]==["20010","20020","20030"]
    lga.check_native(e["native"],before)


@pytest.mark.parametrize("problem", ["rent", "id", "duplicate", "geometry", "count"])
def test_geojson_damage_is_rejected(example,problem):
    expected=lga.to_web_geojson(example["mapped"]); actual=deepcopy(expected)
    if problem=="rent": actual["features"][0]["properties"]["median_weekly_rent"]+=1
    elif problem=="id": actual["features"][0]["id"]="99999"
    elif problem=="duplicate": actual["features"][1]["id"]=actual["features"][0]["id"]
    elif problem=="geometry": actual["features"][0]["geometry"]=None
    elif problem=="count": actual["features"].pop()
    with pytest.raises(ValueError): lga.check_geojson(actual,expected)


def test_export_roundtrip_and_repeat_build(example,tmp_path):
    e=example
    first=lga.export_geography(tmp_path,e["native"],e["crosswalk"],e["mapped"],e["geo_spec"],{},source_rents=e["latest"])
    assert first["gpkg_readback_matches"] and first["geojson_readback_matches"] and first["csv_readback_matches"]
    assert first["quality"]["previous_exports_compared"]==[]
    second=lga.export_geography(tmp_path,e["native"],e["crosswalk"],e["mapped"],e["geo_spec"],{},source_rents=e["latest"])
    assert len(second["quality"]["previous_exports_compared"])==4
    back=gpd.read_file(tmp_path/lga.GPKG_REL,engine="pyogrio")
    assert back.geom_type.tolist()==["Polygon","Polygon","MultiPolygon"]


def test_previous_file_mismatch_is_not_overwritten(example,tmp_path):
    e=example
    lga.export_geography(tmp_path,e["native"],e["crosswalk"],e["mapped"],e["geo_spec"],{},source_rents=e["latest"])
    path=tmp_path/lga.GEOJSON_REL
    doc=json.loads(path.read_text()); doc["features"][0]["properties"]["median_weekly_rent"]+=123
    path.write_text(json.dumps(doc)); before=lga.fingerprint(path)
    with pytest.raises(ValueError): lga.export_geography(tmp_path,e["native"],e["crosswalk"],e["mapped"],e["geo_spec"],{},source_rents=e["latest"])
    assert lga.fingerprint(path)==before


def test_check_only_writes_nothing(example,tmp_path):
    e=example
    result=lga.export_geography(tmp_path,e["native"],e["crosswalk"],e["mapped"],e["geo_spec"],{},source_rents=e["latest"],check_only=True)
    assert result["files_written"]==0
    assert list(tmp_path.iterdir())==[]


def test_changed_source_fingerprint_is_rejected(tmp_path):
    p=tmp_path/"input.txt"; p.write_text("original")
    hashes={p:lga.fingerprint(p)}; p.write_text("changed")
    with pytest.raises(ValueError): lga.verify_fingerprints(hashes)


def test_registry_preserves_other_rows_and_custom_notes(example,tmp_path):
    path=tmp_path/"registry.csv"
    path.write_text("dataset_id,status,notes,download_date\nrent,cleaned_validated,keep me,\nboundaries,not_downloaded,my notes,2026-10-09\ngtfs,not_downloaded,untouched,\n")
    spec={"publisher_page":"https://example.invalid/boundaries","filename":"fixture.zip","sha256":"a"*64,"layer":"fixture"}
    text=lga.registry_update_text(path,spec); rows=list(csv.DictReader(io.StringIO(text)))
    assert rows[0]["status"]=="cleaned_validated" and rows[0]["notes"]=="keep me"
    assert rows[1]["status"]=="matched_validated" and rows[1]["notes"]=="my notes" and rows[1]["download_date"]=="2026-10-09"
    assert rows[2]["status"]=="not_downloaded" and rows[2]["notes"]=="untouched"
    assert lga.registry_update_text(path,spec)==text


@pytest.mark.parametrize("content", ["dataset_id,status\nrent,ok\n", "dataset_id,status\nboundaries,a\nboundaries,b\n",
    "dataset_id,status\nboundaries,ok,EXTRA\n", "dataset_id,status\nboundaries\n"])
def test_malformed_registry_rejected(tmp_path,content):
    path=tmp_path/"registry.csv"; path.write_text(content)
    with pytest.raises(ValueError): lga.registry_update_text(path,{})


def test_boundary_zip_fingerprint_check_before_read(tmp_path):
    p=tmp_path/"fixture.zip"; p.write_bytes(b"not a real archive")
    with pytest.raises(ValueError,match="fingerprint"):
        lga.read_boundaries(p,{"sha256":"a"*64})


@pytest.fixture
def national_fixture(example):
    councils=example["councils"].copy()
    extras=gpd.GeoDataFrame({"LGA_CODE25":["29399","29499","29799","10010"],
        "LGA_NAME25":["Unincorporated Vic","No usual address (Vic.)","Migratory - Offshore - Shipping (Vic.)","Fixture NSW"],
        "STE_CODE21":["2","2","2","1"], "STE_NAME21":["Victoria"]*3+["New South Wales"],
        "AUS_CODE21":["AUS"]*4,"AUS_NAME21":["Australia"]*4,"AREASQKM":[1.0,0.0,0.0,1.0]},
        geometry=[box(145.1,-38,145.2,-37.9),None,None,box(150,-34,150.1,-33.9)],crs=7844)
    full=pd.concat([councils,extras],ignore_index=True)
    spec={"source_columns":full.columns.tolist(),"native_epsg":7844,"national_records":7,
          "national_null_geometry":2,"state_code":"2","state_name":"Victoria","state_records":6,
          "council_records":3,"nonspatial_codes":["29499","29799"],
          "excluded_codes":{"29399":"unincorporated","29499":"no usual address","29799":"nonspatial"}}
    return full,spec


def test_special_categories_are_documented_not_assigned_fake_shapes(national_fixture):
    full,spec=national_fixture
    councils,audit,excluded=lga.audit_boundaries(full,spec)
    assert len(councils)==3
    assert set(excluded.LGA_CODE25)=={"29399","29499","29799"}
    assert audit.null_geometry.tolist()==[2,2,0]


@pytest.mark.parametrize("problem",["crs","record_count","duplicate_code","state_name","council_null","nonspatial_code","invalid_polygon"])
def test_changed_boundary_inventory_is_rejected(national_fixture,problem):
    full,spec=national_fixture; full=full.copy()
    if problem=="crs": full=full.set_crs(4326,allow_override=True)
    elif problem=="record_count": full=full.iloc[1:]
    elif problem=="duplicate_code": full.loc[1,"LGA_CODE25"]=full.loc[0,"LGA_CODE25"]
    elif problem=="state_name": full.loc[0,"STE_NAME21"]="Other"
    elif problem=="council_null": full.at[0,"geometry"]=None
    elif problem=="nonspatial_code": full.loc[4,"LGA_CODE25"]="29998"
    elif problem=="invalid_polygon": full.at[0,"geometry"]=Polygon([(144,-38),(145,-37),(144,-37),(145,-38),(144,-38)])
    with pytest.raises(ValueError): lga.audit_boundaries(full,spec)


def test_export_rejects_rent_changed_after_join(example,tmp_path):
    e=example; changed=e["mapped"].copy(); changed.at[0,"median_weekly_rent"]+=1
    with pytest.raises(AssertionError):
        lga.export_geography(tmp_path,e["native"],e["crosswalk"],changed,e["geo_spec"],{},source_rents=e["latest"])
    assert list(tmp_path.iterdir())==[]
