"""Reusable, read-only ingestion of the audited DFFH LGA rental workbook.

This module preserves the 14-column contract from 02_clean_rental_data.ipynb.
There is no download, imputation, geographic-name guessing or model training.
Validation raises explicit errors, so it remains active under `python -O`.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pandas as pd

AGGREGATE_LABELS = {"Group Total", "Metro", "Non-Metro", "Victoria"}
KEY_COLUMNS = ["rental_area_name", "quarter", "property_type"]
COLUMN_ORDER = [
    "rental_area_name", "source_region", "area_type", "property_type",
    "quarter", "quarter_end", "published_count", "median_weekly_rent",
    "source_file", "source_sheet", "source_reporting_quarter", "source_excel_row",
    "source_count_cell", "source_median_cell",
]
TEXT_COLUMNS = [c for c in COLUMN_ORDER if c not in {
    "quarter_end", "published_count", "median_weekly_rent", "source_excel_row"
}]


def require(condition: bool, message: str) -> None:
    """Fail with a useful message; do not silently drop invalid observations."""
    if not condition:
        raise ValueError(message)


def fingerprint(path: str | Path) -> str:
    """Return a source/content fingerprint without modifying the file."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_snapshot(path: str | Path) -> dict[str, Any]:
    """Load the reviewed source contract, not settings from notebook memory."""
    with Path(path).open(encoding="utf-8") as handle:
        spec = json.load(handle)
    required = {
        "filename", "sha256", "sheet", "property_type", "reporting_quarter",
        "first_quarter", "last_quarter", "raw_shape", "all_lga_count",
        "metro_group_counts", "publisher_page",
    }
    require(isinstance(spec, dict), "Snapshot configuration must be a JSON object.")
    require(required.issubset(spec), f"Snapshot configuration needs: {sorted(required)}")
    require(bool(re.fullmatch(r"[0-9a-f]{64}", spec["sha256"])), "Invalid source SHA-256.")
    require(Path(spec["filename"]).name == spec["filename"], "Use a filename, not a path, in the snapshot.")
    return spec


def read_workbook(path: str | Path, spec: dict[str, Any]) -> pd.DataFrame:
    """Read the exact audited file; a new snapshot must be audited separately."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Place the unchanged rental workbook here: {path}")
    require(fingerprint(path) == spec["sha256"],
            "Workbook fingerprint differs from the audit. Do not edit the hash to bypass this; re-audit the file.")
    raw = pd.read_excel(path, sheet_name=spec["sheet"], header=None,
                        dtype=object, keep_default_na=False, engine="openpyxl")
    require(fingerprint(path) == spec["sha256"], "Source changed while it was being read.")
    return raw


def excel_column_name(position: int) -> str:
    """Convert a zero-based position to an Excel column label."""
    require(isinstance(position, int) and not isinstance(position, bool) and position >= 0,
            "Column position must be a non-negative integer.")
    number, letters = position + 1, ""
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def cell_coordinates(address: str) -> tuple[int, int]:
    """Validate an A1 address and return its zero-based row and column."""
    match = re.fullmatch(r"([A-Z]+)([1-9][0-9]*)", str(address))
    require(match is not None, f"Invalid Excel cell address: {address!r}")
    letters, row = match.groups()
    column = 0
    for letter in letters:
        column = column * 26 + ord(letter) - ord("A") + 1
    return int(row) - 1, column - 1


def parse_quarter(value: object) -> str:
    """Parse an English quarter-ending label, independently of OS locale."""
    label = " ".join(str(value).split())
    match = re.fullmatch(r"(Mar|Jun|Sep|Dec) ([0-9]{4})", label)
    require(match is not None, f"Expected a quarter-ending label such as 'Sep 2025', got {value!r}.")
    month, year = match.groups()
    return f"{year}Q{dict(Mar=1, Jun=2, Sep=3, Dec=4)[month]}"


def quarter_map(raw: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    """Verify paired Count/Median headers and an uninterrupted time sequence."""
    require(raw.shape[1] >= 4 and (raw.shape[1] - 2) % 2 == 0,
            "Unpaired quarter measurement column.")
    records = []
    for count_pos in range(2, raw.shape[1], 2):
        median_pos = count_pos + 1
        label = " ".join(str(raw.iat[1, count_pos]).split())
        other_label = " ".join(str(raw.iat[1, median_pos]).split())
        measures = (str(raw.iat[2, count_pos]).strip(), str(raw.iat[2, median_pos]).strip())
        require(label == other_label and measures == ("Count", "Median"),
                f"Unexpected Count/Median header pair at {excel_column_name(count_pos)}.")
        records.append({"quarter": parse_quarter(label), "count_pos": count_pos,
                        "median_pos": median_pos})
    mapping = pd.DataFrame(records)
    expected = pd.period_range(spec["first_quarter"], spec["last_quarter"], freq="Q").astype(str).tolist()
    require(mapping["quarter"].tolist() == expected,
            "Quarter sequence has a gap, duplicate, wrong order or changed coverage.")
    return mapping


def select_metro_lgas(raw: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    """Fill regional labels only. Retain original LGA names and source row IDs."""
    metadata = raw.iloc[3:, :2].copy()
    metadata.columns = ["source_region", "rental_area_name"]
    metadata["source_excel_row"] = metadata.index + 1
    for column in ["source_region", "rental_area_name"]:
        metadata[column] = metadata[column].astype("string").str.strip().replace("", pd.NA)
    metadata["source_region"] = metadata["source_region"].ffill()
    all_lgas = metadata.loc[metadata["rental_area_name"].notna()
                           & ~metadata["rental_area_name"].isin(AGGREGATE_LABELS)].copy()
    require(len(all_lgas) == spec["all_lga_count"], "Individual-LGA inventory differs from the audit.")
    metro = all_lgas.loc[all_lgas["source_region"].isin(spec["metro_group_counts"])].copy()
    require(not metro["rental_area_name"].duplicated().any(), "Duplicate metropolitan LGA name.")
    require(metro.groupby("source_region").size().to_dict() == spec["metro_group_counts"],
            "Metropolitan group sizes differ from the audited contract.")
    return metro


def parse_published_measure(values: pd.Series, *, integer: bool) -> pd.Series:
    """Preserve blanks/hyphens as missing; reject malformed or impossible values."""
    text = values.astype("string").str.strip().replace({"": pd.NA, "-": pd.NA})
    numeric = pd.to_numeric(text, errors="coerce")
    unexpected = text.notna() & numeric.isna()
    require(not unexpected.any(), f"Unexpected source text: {text.loc[unexpected].tolist()[:5]}")
    present = numeric.dropna()
    require(all(math.isfinite(float(v)) for v in present), "Non-finite count or rent.")
    require(not (present < 0).any(), "Negative count or rent.")
    if integer:
        require(not present.mod(1).ne(0).any(), "Published counts must be whole numbers.")
        try:
            return numeric.astype("Int64")
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("Count does not fit the Int64 data type.") from error
    return numeric.astype("Float64").astype("float64")


def build_panel(raw: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    """Pure transformation: source frame in, 14-column analytical frame out."""
    require(raw.shape == tuple(spec["raw_shape"]), "Raw worksheet shape differs from the audit.")
    require(raw.index.equals(pd.RangeIndex(len(raw))), "Expected unchanged zero-based source row positions.")
    require(str(raw.iat[1, 0]).strip() == spec["property_type"], "Wrong property-category label in A2.")
    metro = select_metro_lgas(raw, spec)
    mapping = quarter_map(raw, spec)
    parts = []
    for q in mapping.itertuples(index=False):
        part = metro.copy()
        part["quarter"] = q.quarter
        part["property_type"] = spec["property_type"]
        part["published_count"] = raw.loc[metro.index].iloc[:, q.count_pos].to_numpy()
        part["median_weekly_rent"] = raw.loc[metro.index].iloc[:, q.median_pos].to_numpy()
        part["source_count_cell"] = excel_column_name(q.count_pos) + part["source_excel_row"].astype(str)
        part["source_median_cell"] = excel_column_name(q.median_pos) + part["source_excel_row"].astype(str)
        parts.append(part)
    panel = pd.concat(parts, ignore_index=True)
    panel["published_count"] = parse_published_measure(panel["published_count"], integer=True)
    panel["median_weekly_rent"] = parse_published_measure(panel["median_weekly_rent"], integer=False)
    panel["quarter_end"] = pd.PeriodIndex(panel["quarter"], freq="Q").to_timestamp(how="end").normalize()
    panel["quarter_end"] = panel["quarter_end"].astype("datetime64[ns]")
    panel["area_type"] = "LGA"
    panel["source_file"] = spec["filename"]
    panel["source_sheet"] = spec["sheet"]
    panel["source_reporting_quarter"] = spec["reporting_quarter"]
    panel["source_excel_row"] = panel["source_excel_row"].astype("int64")
    for column in TEXT_COLUMNS:
        panel[column] = panel[column].astype("string")
    panel = panel[COLUMN_ORDER].sort_values(
        ["rental_area_name", "property_type", "quarter_end"], kind="stable"
    ).reset_index(drop=True)
    validate_panel(panel, raw, spec)
    return panel


def validate_panel(panel: pd.DataFrame, raw: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    """Check types, complete coverage and every source coordinate/value.

    Missing numeric observations are rejected for THIS complete audited metro
    snapshot; the standalone numeric parser still preserves missing markers.
    """
    require(panel.columns.tolist() == COLUMN_ORDER, "Output schema differs from the 14-column contract.")
    require(panel[KEY_COLUMNS].notna().all().all(), "A key contains a missing value.")
    require(not panel.duplicated(KEY_COLUMNS).any(), "Duplicate LGA-quarter-category key.")
    metro = select_metro_lgas(raw, spec)
    mapping = quarter_map(raw, spec)
    expected_quarters = mapping["quarter"].tolist()
    require(len(panel) == len(metro) * len(mapping), "Unexpected panel row count.")
    require(sorted(panel["rental_area_name"].unique()) == sorted(metro["rental_area_name"]),
            "Output LGA inventory differs from selected source rows.")
    for column, value in {
        "property_type": spec["property_type"], "area_type": "LGA",
        "source_file": spec["filename"], "source_sheet": spec["sheet"],
        "source_reporting_quarter": spec["reporting_quarter"],
    }.items():
        require(panel[column].notna().all() and panel[column].eq(value).all(), f"Invalid {column}.")
    require(not panel["rental_area_name"].isin(AGGREGATE_LABELS).any(), "An aggregate was included as an LGA.")
    require(pd.api.types.is_integer_dtype(panel["published_count"]), "Count must have an integer dtype.")
    require(pd.api.types.is_integer_dtype(panel["source_excel_row"]), "Source row must have an integer dtype.")
    require(pd.api.types.is_numeric_dtype(panel["median_weekly_rent"]), "Rent must have a numeric dtype.")
    require(pd.api.types.is_datetime64_any_dtype(panel["quarter_end"]), "quarter_end must be a date dtype.")
    for column in ["published_count", "median_weekly_rent"]:
        require(panel[column].notna().all(), f"Missing {column} in this complete snapshot.")
        require(all(math.isfinite(float(v)) for v in panel[column]), f"Non-finite {column}.")
        require(panel[column].gt(0).all(), f"Non-positive {column} in this audited snapshot.")
    expected_dates = pd.PeriodIndex(panel["quarter"], freq="Q").to_timestamp(how="end").normalize()
    require(pd.DatetimeIndex(panel["quarter_end"]).equals(expected_dates), "Quarter labels and end dates disagree.")
    for _, group in panel.groupby(["rental_area_name", "property_type"], sort=False):
        require(group.sort_values("quarter_end")["quarter"].tolist() == expected_quarters,
                "An LGA is missing quarters or has altered coverage.")

    # Validate the meaning of the addresses, not just their numeric values.
    source_values_verified = 0
    headers = {}
    for q in mapping.itertuples(index=False):
        headers[q.count_pos] = (q.quarter, "Count")
        headers[q.median_pos] = (q.quarter, "Median")
    for row in panel.itertuples(index=False):
        source_row = int(row.source_excel_row) - 1
        require(source_row in metro.index, "Source row does not refer to a selected metropolitan LGA.")
        require(metro.at[source_row, "rental_area_name"] == row.rental_area_name, "Source LGA label mismatch.")
        require(metro.at[source_row, "source_region"] == row.source_region, "Source region mismatch.")
        for address, value, measure in [
            (row.source_count_cell, row.published_count, "Count"),
            (row.source_median_cell, row.median_weekly_rent, "Median"),
        ]:
            cell_row, cell_col = cell_coordinates(address)
            require(cell_row == source_row and headers.get(cell_col) == (row.quarter, measure),
                    f"Wrong source coordinate or measure: {address}.")
            try:
                source_value = float(raw.iat[cell_row, cell_col])
            except (TypeError, ValueError) as error:
                raise ValueError(f"Source value is not numeric: {address}.") from error
            require(source_value == float(value), f"Source value mismatch at {address}.")
            source_values_verified += 1
    return {
        "rows": len(panel), "columns": panel.shape[1], "lga_count": len(metro),
        "quarter_count": len(mapping), "first_quarter": expected_quarters[0],
        "last_quarter": expected_quarters[-1], "duplicate_keys": 0,
        "missing_count_values": 0, "missing_rent_values": 0,
        "source_values_verified": source_values_verified,
    }


def read_panel_csv(path: str | Path) -> pd.DataFrame:
    """Restore the explicit contract because CSV does not carry a schema."""
    types = {c: "string" for c in TEXT_COLUMNS}
    types.update(published_count="Int64", median_weekly_rent="float64", source_excel_row="int64")
    frame = pd.read_csv(path, dtype=types, parse_dates=["quarter_end"], keep_default_na=False)
    frame["quarter_end"] = frame["quarter_end"].astype("datetime64[ns]")
    return frame


def require_equal(expected: pd.DataFrame, actual: pd.DataFrame, label: str) -> None:
    """Ignore storage-specific string backends, never values or row order."""
    try:
        pd.testing.assert_frame_equal(expected, actual, check_dtype=False, check_exact=True)
    except AssertionError as error:
        raise ValueError(f"{label} does not match the rebuilt panel. No output files were replaced.") from error


def compare_existing(panel: pd.DataFrame, output_dir: str | Path) -> list[str]:
    """Compare old notebook/pipeline exports BEFORE any overwrite."""
    output_dir = Path(output_dir)
    compared = []
    for filename in ["rent_quarterly.csv", "rent_quarterly.parquet"]:
        path = output_dir / filename
        if path.is_file():
            actual = read_panel_csv(path) if path.suffix == ".csv" else pd.read_parquet(path, engine="pyarrow")
            require_equal(panel, actual, filename)
            compared.append(filename)
    return compared


def write_outputs(panel: pd.DataFrame, raw: pd.DataFrame, spec: dict[str, Any],
                  output_dir: str | Path, source_path: str | Path) -> dict[str, Any]:
    """Validate, stage both formats, read them back, then replace derived files.

    Individual files are replaced only after all value comparisons succeed.
    This is not a multi-file database transaction; avoid simultaneous writers.
    """
    output_dir, source_path = Path(output_dir), Path(source_path)
    require(source_path.resolve().parent != output_dir.resolve(), "Do not write derived files into the source folder.")
    require(fingerprint(source_path) == spec["sha256"], "Source fingerprint changed before writing.")
    quality = validate_panel(panel, raw, spec)
    compared = compare_existing(panel, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".rent-staging-", dir=output_dir) as temp:
        temp = Path(temp)
        parquet_path, csv_path = temp / "rent_quarterly.parquet", temp / "rent_quarterly.csv"
        panel.to_parquet(parquet_path, index=False, engine="pyarrow")
        panel.to_csv(csv_path, index=False, date_format="%Y-%m-%d", encoding="utf-8")
        for label, reloaded in [
            ("Parquet read-back", pd.read_parquet(parquet_path, engine="pyarrow")),
            ("CSV read-back", read_panel_csv(csv_path)),
        ]:
            validate_panel(reloaded, raw, spec)
            require_equal(panel, reloaded, label)
        require(fingerprint(source_path) == spec["sha256"], "Source changed during the build.")
        quality["source_unchanged"] = True
        manifest = {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "builder": "scripts/build_rent_panel.py", "pandas_version": pd.__version__,
            "source": {"filename": spec["filename"], "publisher_page": spec["publisher_page"],
                       "sha256": spec["sha256"], "worksheet": spec["sheet"],
                       "property_label": spec["property_type"], "reporting_quarter": spec["reporting_quarter"]},
            "geography": {"definition": "Source's three metropolitan groups; individual LGA rows only",
                          "groups": spec["metro_group_counts"]},
            "analytical_key": KEY_COLUMNS, "quality": quality,
            "previous_exports_compared": compared,
            "parquet_readback_matches": True, "csv_readback_matches": True,
            "columns": [{"name": c, "dtype": str(panel[c].dtype)} for c in panel.columns],
            "output_sha256": {p.name: fingerprint(p) for p in [parquet_path, csv_path]},
        }
        report = temp / "rent_quality_report.json"
        report.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        for file in [parquet_path, csv_path, report]:
            file.replace(output_dir / file.name)
    return manifest


def updated_registry_text(path: str | Path, spec: dict[str, Any]) -> str:
    """Prepare a minimal registry update; preserve custom columns/other rows.

    No acquisition date, licence or publication date is invented. Reporting
    quarter and observation coverage are taken from the audited snapshot.
    """
    import io
    path = Path(path)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    require({"dataset_id", "status"}.issubset(fields), "Registry requires dataset_id and status columns.")
    require(all(None not in row and all(v is not None for v in row.values()) for row in rows),
            "Malformed CSV row in the data registry; review it before updating.")
    matches = [row for row in rows if row["dataset_id"] == "rent"]
    require(len(matches) == 1, "Registry must contain exactly one dataset_id=rent row.")
    changes = {
        "status": "cleaned_validated", "source_filename": spec["filename"],
        "source_sha256": spec["sha256"], "source_sheet": spec["sheet"],
        "reporting_quarter": spec["reporting_quarter"],
        "observation_start_quarter": spec["first_quarter"],
        "observation_end_quarter": spec["last_quarter"],
        "processed_scope": f"{sum(spec["metro_group_counts"].values())} source-group metropolitan LGAs; {spec["property_type"]} only",
        "processed_file": "data/processed/rent_quarterly.parquet",
        "build_command": "python scripts/build_rent_panel.py --update-registry",
    }
    for column in changes:
        if column not in fields:
            fields.append(column)
    matches[0].update(changes)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()
