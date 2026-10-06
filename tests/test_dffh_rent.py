"""Synthetic tests: no official XLSX, network or private local path required."""
from __future__ import annotations

import copy
import csv
import hashlib
import io
from pathlib import Path

import pandas as pd
import pytest

from homereach.io.dffh_rent import (
    COLUMN_ORDER, KEY_COLUMNS, build_panel, cell_coordinates, compare_existing,
    excel_column_name, fingerprint, load_snapshot, parse_published_measure,
    parse_quarter, quarter_map, read_panel_csv, read_workbook, require_equal,
    select_metro_lgas, updated_registry_text, validate_panel, write_outputs,
)


@pytest.fixture
def source():
    """Three fictional metro LGAs, one rural LGA, two quarters and totals."""
    raw = pd.DataFrame([
        ["Quarterly median rents by Local Government Area", "", "", "", "", ""],
        ["2 bedroom flats", "", "Jun 2025", "Jun 2025", "Sep 2025", "Sep 2025"],
        ["", "", "Count", "Median", "Count", "Median"],
        ["Rural", "Fixture Rural", 4, 200, 5, 210],
        ["", "Group Total", 4, 200, 5, 210],
        ["North and West Metro", "Fixture A", 12, 400, 14, 420],
        ["", "Fixture B", 8, 450, 10, 460],
        ["", "Group Total", 20, 430, 24, 440],
        ["Eastern Metro", "Fixture C", 9, 500, 11, 520],
        ["", "Group Total", 9, 500, 11, 520],
        ["Table Total", "Victoria", 33, 410, 40, 430],
        ["", "", "", "", "", ""],
        ["METRO NON-METRO", "Metro", 29, 450, 35, 470],
        ["", "Non-Metro", 4, 200, 5, 210],
        ["", "Victoria", 33, 410, 40, 430],
    ], dtype=object)
    spec = {
        "filename": "fixture.xlsx", "sha256": hashlib.sha256(b"synthetic source").hexdigest(),
        "sheet": "2br Flat", "property_type": "2 bedroom flats", "reporting_quarter": "2025Q3",
        "first_quarter": "2025Q2", "last_quarter": "2025Q3", "raw_shape": [15, 6],
        "all_lga_count": 4, "metro_group_counts": {"North and West Metro": 2, "Eastern Metro": 1},
        "publisher_page": "https://example.invalid/synthetic-only",
    }
    return raw, spec


@pytest.mark.parametrize("position,label", [(0,"A"),(25,"Z"),(26,"AA"),(213,"HF")])
def test_column_labels(position, label):
    assert excel_column_name(position) == label


@pytest.mark.parametrize("position", [-1, 1.5, True])
def test_bad_column_positions_fail(position):
    with pytest.raises(ValueError):
        excel_column_name(position)


def test_cell_address_is_zero_based():
    assert cell_coordinates("HF63") == (62, 213)


@pytest.mark.parametrize("address", ["A0", "1A", "A", "A-1", "A1suffix"])
def test_malformed_cell_addresses_fail(address):
    with pytest.raises(ValueError):
        cell_coordinates(address)


@pytest.mark.parametrize("label,quarter", [("Jun 1999","1999Q2"),("Sep\n2025","2025Q3"),("Mar 2025","2025Q1"),("Dec 2025","2025Q4")])
def test_quarter_parser(label, quarter):
    assert parse_quarter(label) == quarter


@pytest.mark.parametrize("label", ["Apr 2025", "Sep 25", "unknown"])
def test_invalid_quarter_label_fails(label):
    with pytest.raises(ValueError):
        parse_quarter(label)


def test_missing_is_not_zero():
    result = parse_published_measure(pd.Series([12,"-","",None,"0"]), integer=True)
    assert str(result.dtype) == "Int64"
    assert result.iloc[1:4].isna().all()
    assert result.iloc[0] == 12 and result.iloc[4] == 0


@pytest.mark.parametrize("value,integer", [("unknown",False),(-5,False),(2.5,True),("inf",False),(True,True)])
def test_bad_measure_fails(value, integer):
    with pytest.raises(ValueError):
        parse_published_measure(pd.Series([value]), integer=integer)


def test_fractional_rent_is_valid():
    assert parse_published_measure(pd.Series([600.5]), integer=False).iloc[0] == 600.5


def test_metadata_fill_excludes_totals_and_rural_rows(source):
    raw, spec = source
    metro = select_metro_lgas(raw, spec)
    assert metro["rental_area_name"].tolist() == ["Fixture A","Fixture B","Fixture C"]
    assert metro.loc[6,"source_region"] == "North and West Metro"
    assert metro["source_excel_row"].tolist() == [6,7,9]


def test_build_matches_expected_values_and_keeps_input_unchanged(source):
    raw, spec = source
    original = raw.copy(deep=True)
    panel = build_panel(raw, spec)
    assert panel.shape == (6,14) and panel.columns.tolist() == COLUMN_ORDER
    assert not panel.duplicated(KEY_COLUMNS).any()
    assert panel["published_count"].tolist() == [12,14,8,10,9,11]
    assert panel["median_weekly_rent"].tolist() == [400,420,450,460,500,520]
    assert panel["source_median_cell"].tolist() == ["D6","F6","D7","F7","D9","F9"]
    assert panel.iloc[1]["quarter_end"] == pd.Timestamp("2025-09-30")
    assert validate_panel(panel, raw, spec)["source_values_verified"] == 12
    pd.testing.assert_frame_equal(raw, original)


@pytest.mark.parametrize("mutation", ["swapped_measures","different_pair_dates","duplicate_quarter"])
def test_header_corruption_is_rejected(source, mutation):
    raw, spec = source
    if mutation == "swapped_measures":
        raw.iat[2,2], raw.iat[2,3] = "Median", "Count"
    elif mutation == "different_pair_dates":
        raw.iat[1,3] = "Sep 2025"
    else:
        raw.iat[1,4] = raw.iat[1,5] = "Jun 2025"
    with pytest.raises(ValueError):
        quarter_map(raw, spec)


def test_quarter_gap_is_rejected(source):
    raw, spec = source
    spec["last_quarter"] = "2025Q4"
    raw.iat[1,4] = raw.iat[1,5] = "Dec 2025"
    with pytest.raises(ValueError, match="Quarter sequence"):
        quarter_map(raw, spec)


def test_changed_shape_or_category_rejected(source):
    raw, spec = source
    with pytest.raises(ValueError, match="shape"):
        build_panel(raw.iloc[:,:-1], spec)
    raw.iat[1,0] = "3 bedroom flats"
    with pytest.raises(ValueError, match="category"):
        build_panel(raw, spec)


def test_missing_rent_is_not_filled_from_previous_area(source):
    raw, spec = source
    raw.iat[6,3] = "-"
    with pytest.raises(ValueError, match="Missing median_weekly_rent"):
        build_panel(raw, spec)


def test_wrong_group_sizes_and_duplicate_names_rejected(source):
    raw, spec = source
    wrong = copy.deepcopy(spec)
    wrong["metro_group_counts"]["Eastern Metro"] = 2
    with pytest.raises(ValueError, match="group sizes"):
        select_metro_lgas(raw, wrong)
    raw.iat[6,1] = "Fixture A"
    with pytest.raises(ValueError, match="Duplicate metropolitan"):
        select_metro_lgas(raw, spec)


@pytest.mark.parametrize("mutation", ["duplicate","drop_row","wrong_rent","wrong_cell","wrong_date","wrong_region"])
def test_validation_catches_damaged_outputs(source, mutation):
    raw, spec = source
    panel = build_panel(raw, spec)
    if mutation == "duplicate":
        panel = pd.concat([panel.iloc[[1]],panel.iloc[1:]],ignore_index=True)
    elif mutation == "drop_row":
        panel = panel.iloc[1:].copy()
    elif mutation == "wrong_rent":
        panel.loc[0,"median_weekly_rent"] = 999.0
    elif mutation == "wrong_cell":
        panel.loc[0,"source_median_cell"] = "C6"
    elif mutation == "wrong_date":
        panel.loc[0,"quarter_end"] = pd.Timestamp("2025-01-01")
    else:
        panel.loc[0,"source_region"] = "Eastern Metro"
    with pytest.raises(ValueError):
        validate_panel(panel, raw, spec)


def test_csv_roundtrip_and_existing_export_comparison(source, tmp_path):
    raw, spec = source
    panel = build_panel(raw, spec)
    path = tmp_path / "rent_quarterly.csv"
    panel.to_csv(path,index=False,date_format="%Y-%m-%d")
    require_equal(panel,read_panel_csv(path),"CSV")
    assert compare_existing(panel,tmp_path) == ["rent_quarterly.csv"]
    changed = panel.copy()
    changed.loc[0,"median_weekly_rent"] = 998.0
    old_bytes = path.read_bytes()
    with pytest.raises(ValueError,match="does not match"):
        compare_existing(changed,tmp_path)
    assert path.read_bytes() == old_bytes


def test_wrong_fingerprint_fails_before_excel_read(source, tmp_path):
    _, spec = source
    path = tmp_path / "fixture.xlsx"
    path.write_bytes(b"different source")
    with pytest.raises(ValueError, match="fingerprint"):
        read_workbook(path,spec)


def test_missing_workbook_has_clear_error(source, tmp_path):
    _, spec = source
    with pytest.raises(FileNotFoundError, match="unchanged rental workbook"):
        read_workbook(tmp_path / "absent.xlsx",spec)


def test_registry_preserves_notes_other_sources_and_is_repeatable(source, tmp_path):
    _, spec = source
    path = tmp_path / "data_registry.csv"
    original = "dataset_id,status,my_notes,download_date\nrent,not_downloaded,keep my note,\ngtfs,not_downloaded,transport untouched,\n"
    path.write_text(original)
    updated = updated_registry_text(path,spec)
    assert path.read_text() == original  # preparing is not writing
    rows = list(csv.DictReader(io.StringIO(updated)))
    assert rows[0]["status"] == "cleaned_validated"
    assert rows[0]["my_notes"] == "keep my note" and rows[0]["download_date"] == ""
    assert rows[1]["status"] == "not_downloaded" and rows[1]["my_notes"] == "transport untouched"
    assert rows[1]["source_sha256"] == ""
    path.write_text(updated)
    assert updated_registry_text(path,spec) == updated


@pytest.mark.parametrize("contents", ["dataset_id,status\ngtfs,new\n", "dataset_id,status\nrent,new\nrent,new\n"])
def test_registry_requires_one_rent_record(source, tmp_path, contents):
    _, spec = source
    path = tmp_path / "registry.csv"
    path.write_text(contents)
    with pytest.raises(ValueError, match="exactly one"):
        updated_registry_text(path,spec)


def test_config_loads_reviewed_json(source, tmp_path):
    import json
    _, spec = source
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(spec))
    assert load_snapshot(path) == spec


def test_export_parquet_csv_and_rerun(source, tmp_path):
    # A skip means Parquet has NOT been tested in that environment. The user's
    # homereach environment and CI requirements both include pyarrow.
    pytest.importorskip("pyarrow", reason="Parquet engine is required for the export integration test")
    raw, spec = source
    source_path = tmp_path / "raw" / "fixture.xlsx"
    source_path.parent.mkdir()
    source_path.write_bytes(b"synthetic source")
    panel = build_panel(raw,spec)
    out = tmp_path / "processed"
    report = write_outputs(panel,raw,spec,out,source_path)
    assert report["quality"]["rows"] == 6
    assert report["previous_exports_compared"] == []
    assert report["parquet_readback_matches"] and report["csv_readback_matches"]
    assert fingerprint(source_path) == spec["sha256"]
    second = write_outputs(panel,raw,spec,out,source_path)
    assert second["previous_exports_compared"] == ["rent_quarterly.csv","rent_quarterly.parquet"]
