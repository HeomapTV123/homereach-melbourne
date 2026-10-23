"""Synthetic tests: never need official source files, a network or a running UI."""
from copy import deepcopy
from pathlib import Path
import json
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon, mapping
from homereach.explorer.analysis import (CODE, safe_ratio, complete_one_to_one, aggregate_lgas, filter_comparison)
from homereach.explorer.bundle import (GEOJSON, MANIFEST, TABLE_NAMES, REPORTS, table_schema, read_table,
                                       compare_csv, validate_geometry_payload, bundle_signature, fingerprint)
from homereach.explorer.charts import rent_service_scatter, rent_history_chart, category_chart, rent_map


@pytest.fixture
def areas():
    return pd.DataFrame({CODE: ["20001", "20002", "20003"], "rental_area_name": ["Fixture A", "Fixture B", "Fixture C"],
                         "abs_lga_name": ["Fixture A", "Fixture B", "Fixture C"], "source_region": ["North", "North", "South"],
                         "median_weekly_rent": [400.0, 600.0, 600.0], "published_count": [10, 20, 30],
                         "am_unique_trip_records": [10, 20, 5], "am_departure_events": [100, 200, 50],
                         "am_served_stop_records": [5, 10, 3], "quarter": ["2025Q3"] * 3,
                         "transport_service_date": ["2026-10-13"] * 3, "source_median_cell": ["HF4", "HF5", "HF6"]})


def geo_for(areas):
    features = []
    for i, row in enumerate(areas.itertuples(index=False)):
        x = 144.9 + i * 0.1; y = -37.9
        poly = Polygon([(x, y), (x+0.05, y), (x+0.05, y+0.05), (x, y+0.05)])
        features.append({"type": "Feature", "id": getattr(row, CODE),
                         "properties": {CODE: getattr(row, CODE), "abs_lga_name": row.abs_lga_name},
                         "geometry": mapping(poly)})
    return json.loads(json.dumps({"type": "FeatureCollection", "features": features}))


def test_default_is_alphabetical_and_not_ranked(areas):
    result = filter_comparison(areas.iloc[::-1])
    assert result.rental_area_name.tolist() == ["Fixture A", "Fixture B", "Fixture C"]
    assert "rank" not in result and "overall_score" not in result


@pytest.mark.parametrize("ceiling,expected", [(0, []), (399, []), (400, ["Fixture A"]), (600, ["Fixture A", "Fixture B", "Fixture C"]), (None, ["Fixture A", "Fixture B", "Fixture C"])])
def test_ceiling_inclusive(areas, ceiling, expected):
    assert filter_comparison(areas, maximum_rent=ceiling).rental_area_name.tolist() == expected


@pytest.mark.parametrize("minimum,expected", [(0, 3), (5, 3), (10, 2), (20, 1), (21, 0)])
def test_trip_filter(areas, minimum, expected):
    assert len(filter_comparison(areas, minimum_am_trips=minimum)) == expected


@pytest.mark.parametrize("regions,expected", [(None, 3), ([], 0), (["North"], 2), (["South"], 1)])
def test_region_filter(areas, regions, expected):
    assert len(filter_comparison(areas, regions=regions)) == expected


@pytest.mark.parametrize("kwargs", [{"maximum_rent": -1}, {"maximum_rent": float("nan")}, {"maximum_rent": float("inf")},
                                    {"minimum_am_trips": -1}, {"minimum_am_trips": 1.5}, {"minimum_am_trips": True},
                                    {"regions": ["Unknown"]}, {"sort_by": "overall_score"}])
def test_invalid_filter_is_not_silently_accepted(areas, kwargs):
    with pytest.raises(ValueError): filter_comparison(areas, **kwargs)


def test_tie_breaking_and_source_unchanged(areas):
    before = areas.copy(deep=True)
    result = filter_comparison(areas, sort_by="median_weekly_rent", ascending=False)
    assert result.rental_area_name.tolist() == ["Fixture B", "Fixture C", "Fixture A"]
    pd.testing.assert_frame_equal(before, areas)


def test_different_dates_preserved_in_filtered_download(areas):
    result = filter_comparison(areas, maximum_rent=500)
    assert result.quarter.tolist() == ["2025Q3"]
    assert result.transport_service_date.tolist() == ["2026-10-13"]


def test_ratios_zero_is_not_missing():
    x = safe_ratio(pd.Series([10, 0, 0]), pd.Series([2, 2, 0]))
    assert x.iloc[0] == 5 and x.iloc[1] == 0 and pd.isna(x.iloc[2])


@pytest.mark.parametrize("problem", ["duplicate", "missing", "null", "overlap"])
def test_reviewed_merge_rejects_bad_keys(problem):
    a = pd.DataFrame({CODE: ["A", "B"], "rent": [500, 600]})
    b = pd.DataFrame({CODE: ["B", "A"], "events": [20, 10]})
    if problem == "duplicate": b.loc[1, CODE] = "B"
    elif problem == "missing": b = b.iloc[:1]
    elif problem == "null": b.loc[1, CODE] = None
    else: b["rent"] = [1, 2]
    with pytest.raises(ValueError): complete_one_to_one(a, b, CODE, "fixture")


def test_join_by_code_not_position():
    a = pd.DataFrame({CODE: ["A", "B"], "rent": [500, 600]})
    b = pd.DataFrame({CODE: ["B", "A"], "events": [20, 10]})
    assert complete_one_to_one(a, b, CODE, "fixture").events.tolist() == [10, 20]


def test_trip_counts_deduplicate_across_service_rows():
    lga = pd.DataFrame({CODE: ["A", "A", "B"], "window": ["am"] * 3,
                        "eligible_departure_events": [2, 3, 1], "near_boundary_events": [0, 0, 0], "extended_time_events": [0, 0, 0]})
    members = pd.DataFrame({CODE: ["A", "A", "B"], "window": ["am"] * 3,
                            "trip_key": ["2:T", "2:T", "2:T"], "route_key": ["2:R"] * 3})
    stops = pd.DataFrame({CODE: ["A", "A", "B"], "window": ["am"] * 3, "stop_key": ["2:S1", "2:S1", "2:S2"]})
    got = aggregate_lgas(lga, members, stops, ["A", "B"], "am")
    assert got.unique_trip_records.tolist() == [1, 1]
    assert got.served_stop_records.tolist() == [1, 1]
    assert got.departure_events.tolist() == [5, 1]
    assert members.trip_key.nunique() == 1  # NOT sum of LGA-specific trip counts (2)


def mixed_table():
    return pd.DataFrame({"code": pd.Series(["02001", "02002"], dtype="string"),
                         "count": pd.Series([0, 2], dtype="int64"),
                         "nullable": pd.Series([1, pd.NA], dtype="Int64"),
                         "ratio": pd.Series([0.0, np.nan], dtype="float64"),
                         "quarter_end": pd.to_datetime(["2025-06-30", "2025-09-30"]).as_unit("ns")})


def test_csv_round_trip_preserves_missing_ratio_and_string_codes(tmp_path):
    frame = mixed_table(); path = tmp_path / "fixture.csv"
    frame.to_csv(path, index=False, date_format="%Y-%m-%d")
    compare_csv(path, frame)
    back = read_table(path, table_schema(frame))
    assert back.code.iloc[0] == "02001" and pd.isna(back.ratio.iloc[1])
    assert str(back.quarter_end.dtype) == "datetime64[ns]"


@pytest.mark.parametrize("change", ["value", "column", "row"])
def test_comparison_detects_changed_export(tmp_path, change):
    frame = mixed_table(); bad = frame.copy()
    if change == "value": bad.loc[0, "count"] = 99
    elif change == "column": bad = bad.rename(columns={"code": "other"})
    else: bad = bad.iloc[:1]
    p = tmp_path / "bad.csv";bad.to_csv(p, index=False)
    with pytest.raises(ValueError): compare_csv(p, frame)


def test_map_payload_valid(areas):
    validate_geometry_payload(geo_for(areas), areas)


@pytest.mark.parametrize("problem", ["missing", "duplicate", "name", "type", "coordinates", "feature_id"])
def test_map_payload_rejects_damage(areas, problem):
    geo = geo_for(areas)
    if problem == "missing": geo["features"].pop()
    elif problem == "duplicate": geo["features"][1] = deepcopy(geo["features"][0])
    elif problem == "name": geo["features"][0]["properties"]["abs_lga_name"] = "wrong"
    elif problem == "type": geo["features"][0]["geometry"] = {"type": "Point", "coordinates": [145, -38]}
    elif problem == "coordinates": geo["features"][0]["geometry"] = mapping(Polygon([(400, 400), (410, 400), (410, 410), (400, 400)]))
    else: geo["features"][0]["id"] = "wrong"
    with pytest.raises(ValueError): validate_geometry_payload(geo, areas)


def test_scatter_contains_source_periods_and_no_regression(areas):
    fig = rent_service_scatter(areas)
    assert sum(len(t.x) for t in fig.data) == 3
    assert all(t.mode == "markers" for t in fig.data)
    assert "2025Q3" in fig.layout.xaxis.title.text and "2026" in fig.layout.yaxis.title.text


def test_history_sorted_chronologically(areas):
    hist = pd.DataFrame({"rental_area_name": ["Fixture A"] * 3, "quarter": ["2025Q3", "2025Q1", "2025Q2"],
                         "quarter_end": pd.to_datetime(["2025-09-30", "2025-03-31", "2025-06-30"]),
                         "median_weekly_rent": [600, 400, 500], "published_count": [10] * 3, "source_median_cell": ["HF4"] * 3})
    assert list(rent_history_chart(hist).data[0].y) == [400, 500, 600]


def test_replacement_zero_stays_visible():
    cats = pd.DataFrame({"service_category": ["labelled_replacement_bus", "tram"], "eligible_departure_events": [0, 10],
                         "unique_trip_records": [0, 2], "served_stop_records": [0, 5]})
    fig = category_chart(cats)
    assert len(fig.data[0].x) == 2 and 0 in fig.data[0].x


def test_map_default_uses_no_external_tiles(areas):
    fig = rent_map(areas, geo_for(areas))
    assert fig.layout.map.style == "white-bg" and len(fig.data[0].locations) == 3


def test_map_online_tiles_are_opt_in(areas):
    assert rent_map(areas, geo_for(areas), online_basemap=True).layout.map.style == "carto-positron"


def seed_signature_fixture(root):
    dest = root / "data/processed/explorer";dest.mkdir(parents=True)
    files = [*TABLE_NAMES, GEOJSON]
    for name in files:(dest / name).write_text("fixture\n")
    for rel in REPORTS:
        p = root / rel;p.parent.mkdir(parents=True, exist_ok=True);p.write_text("{}")
    manifest = {"schema_version": 1, "builder": "scripts/build_explorer_data.py", "check_only": False,
                "output_sha256": {n: fingerprint(dest / n) for n in files}, "output_schemas": {n: {} for n in TABLE_NAMES},
                "upstream_report_sha256": {p: fingerprint(root / p) for p in REPORTS},
                "csv_readback_matches": True, "geojson_readback_matches": True}
    (dest / MANIFEST).write_text(json.dumps(manifest))
    return dest, manifest


def test_missing_bundle_gives_build_instruction(tmp_path):
    with pytest.raises(FileNotFoundError, match="build_explorer_data"):
        bundle_signature(tmp_path)


def test_signature_accepts_unchanged_inventory(tmp_path):
    seed_signature_fixture(tmp_path)
    assert bundle_signature(tmp_path) == bundle_signature(tmp_path)


@pytest.mark.parametrize("problem", ["changed_output", "missing_output", "stale_upstream", "bad_builder", "missing_schema", "check_only", "failed_readback"])
def test_signature_rejects_stale_or_changed_bundle(tmp_path, problem):
    dest, manifest = seed_signature_fixture(tmp_path)
    if problem == "changed_output": (dest / TABLE_NAMES[0]).write_text("changed")
    elif problem == "missing_output": (dest / TABLE_NAMES[0]).unlink()
    elif problem == "stale_upstream": (tmp_path / REPORTS[0]).write_text('{"changed":true}')
    elif problem == "bad_builder": manifest["builder"] = "wrong"
    elif problem == "missing_schema": manifest["output_schemas"].pop(TABLE_NAMES[0])
    elif problem == "check_only": manifest["check_only"] = True
    else: manifest["csv_readback_matches"] = False
    (dest / MANIFEST).write_text(json.dumps(manifest))
    with pytest.raises(ValueError): bundle_signature(tmp_path)
