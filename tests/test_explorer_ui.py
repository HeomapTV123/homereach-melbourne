"""Streamlit AppTest checks with fictional data; official datasets are never needed.

Skipped as a module only when Streamlit is not installed. In the full homereach
or CI environment these ten cases must run, not be treated as already passed.
"""
from copy import deepcopy
from pathlib import Path
import pandas as pd
import pytest

st = pytest.importorskip("streamlit", reason="Streamlit is needed for actual AppTest execution")
from streamlit.testing.v1 import AppTest
from shapely.geometry import Polygon, mapping
from homereach.explorer.bundle import ExplorerBundle
from homereach.explorer.analysis import CODE, CATEGORY_LABELS, AM_WINDOW, DAY_WINDOW


@pytest.fixture
def fixture_bundle():
    rows = []
    for i, (name, region, rent, trips) in enumerate([("Fixture A", "North", 400, 10), ("Fixture B", "North", 600, 20), ("Fixture C", "South", 600, 5)]):
        rows.append({CODE: f"2000{i+1}", "rental_area_name": name, "abs_lga_name": name, "source_region": region,
                     "median_weekly_rent": float(rent), "published_count": 20,
                     "am_unique_trip_records": trips, "am_departure_events": trips*10,
                     "am_served_stop_records": 5, "assigned_stop_records": 6,
                     "assigned_records_without_counted_am_event": 1,
                     "mean_am_events_per_assigned_stop_record": trips*10/6,
                     "mean_am_events_per_served_stop_record": trips*2,
                     "quarter": "2025Q3", "transport_service_date": "2026-10-13", "transport_timezone": "Australia/Melbourne",
                     "source_file": "fictional.xlsx", "source_sheet": "Fixture", "source_median_cell": "D4", "source_count_cell": "C4"})
    areas = pd.DataFrame(rows)
    history = []
    for row in rows:
        for q, value in [("2025Q1", 350), ("2025Q2", 375), ("2025Q3", row["median_weekly_rent"])]:
            history.append({**row, "quarter": q, "quarter_end": pd.Period(q, freq="Q").end_time.normalize(), "median_weekly_rent": value})
    categories = []
    for row in rows:
        for window in (AM_WINDOW, DAY_WINDOW):
            for cat in CATEGORY_LABELS:
                n = 0 if cat == "labelled_replacement_bus" else 10
                categories.append({CODE: row[CODE], "window": window, "service_category": cat,
                                   "eligible_departure_events": n, "unique_trip_records": n//2, "served_stop_records": n//2, "unique_route_records": int(n > 0)})
    features = []
    for i, row in enumerate(rows):
        x=145+i*0.1;y=-38
        features.append({"type": "Feature", "id": row[CODE], "properties": {CODE: row[CODE], "abs_lga_name": row["abs_lga_name"]},
                         "geometry": mapping(Polygon([(x,y),(x+.05,y),(x+.05,y+.05),(x,y+.05)]))})
    tables = {"rent_transport_comparison.csv": areas, "rental_history.csv": pd.DataFrame(history),
              "lga_service_categories.csv": pd.DataFrame(categories),
              "study_area_reconciliation.csv": pd.DataFrame([{"window": AM_WINDOW, "distinct_study_area_trips": 25,
                                                             "sum_of_lga_trip_counts_not_a_study_area_total": 35}]),
              "source_periods.csv": pd.DataFrame([{"component": "rent", "period": "2025Q3", "scope": "Fictional test input",
                                                   "publisher_page": "https://example.com", "source_file": "fixture.csv", "source_sha256": "0"*64}])}
    manifest = {"created_at_utc": "2026-10-22T00:00:00+00:00", "quality": {"fixture": True}, "notebook_tables_compared": []}
    return ExplorerBundle(tables, {"type": "FeatureCollection", "features": features}, manifest)


def page(name, bundle):
    at = AppTest.from_string(f"import streamlit as st\nfrom homereach.explorer.ui import {name}\n"
                             f"st.set_page_config(layout='wide')\n{name}(st.session_state['_fixture'])", default_timeout=30)
    at.session_state["_fixture"] = bundle
    return at.run()


@pytest.mark.parametrize("name", ["render_compare", "render_area", "render_map", "render_method"])
def test_each_real_data_page_runs(name, fixture_bundle):
    at = page(name, fixture_bundle)
    assert not at.exception
    assert any("differently dated" in item.value for item in at.info)


def test_rent_filter_updates_table(fixture_bundle):
    at = page("render_compare", fixture_bundle)
    at.checkbox(key="compare_use_ceiling").set_value(True).run()
    at.number_input(key="compare_ceiling").set_value(400).run()
    assert not at.exception
    assert len(at.dataframe[0].value) == 1
    assert at.dataframe[0].value.iloc[0]["Rental-source LGA"] == "Fixture A"


def test_empty_rent_filter_is_explained(fixture_bundle):
    at = page("render_compare", fixture_bundle)
    at.checkbox(key="compare_use_ceiling").set_value(True).run()
    at.number_input(key="compare_ceiling").set_value(0).run()
    assert not at.exception and len(at.dataframe) == 0
    assert any("No LGAs match" in w.value for w in at.warning)


def test_empty_region_selection_is_explained(fixture_bundle):
    at = page("render_compare", fixture_bundle)
    at.multiselect(key="compare_regions").set_value([]).run()
    assert not at.exception and any("No LGAs match" in w.value for w in at.warning)


def test_area_and_window_can_change(fixture_bundle):
    at = page("render_area", fixture_bundle)
    at.selectbox(key="area_code").set_value("20002").run()
    at.radio(key="area_window").set_value("Complete GTFS service day").run()
    assert not at.exception
    assert any(s.value == "Fixture B" for s in at.subheader)
    assert any(len(d.value) == 4 for d in at.dataframe)


def test_map_background_can_be_selected(fixture_bundle):
    at = page("render_map", fixture_bundle)
    at.checkbox(key="map_online").set_value(True).run()
    assert not at.exception


def test_unbuilt_explorer_has_no_synthetic_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("HOMEREACH_PROJECT_ROOT", str(tmp_path))
    entry = Path(__file__).resolve().parents[1] / "app/Explore.py"
    at = AppTest.from_file(str(entry), default_timeout=30).run()
    assert not at.exception
    assert any("bundle is not ready" in e.value for e in at.error)
    assert any("No synthetic fallback" in e.value for e in at.info)
