from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

QUARTER_PATTERN = re.compile(
    r"^(Mar|Jun|Sep|Dec)[-\s]?\d{2,4}$",
    flags=re.IGNORECASE,
)


def audit_excel_workbook(
    path: str | Path,
    preview_rows: int = 12,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """
    Return a workbook summary and raw previews without assuming its layout.

    Inspect first, then write a parser. This prevents use of the wrong
    header row or measure column.
    """
    workbook_path = Path(path)
    if not workbook_path.exists():
        raise FileNotFoundError(
            f"Rental workbook not found: {workbook_path.resolve()}"
        )

    excel = pd.ExcelFile(workbook_path)
    previews: dict[str, pd.DataFrame] = {}
    summary_rows: list[dict[str, Any]] = []

    for sheet_name in excel.sheet_names:
        raw = pd.read_excel(
            workbook_path,
            sheet_name=sheet_name,
            header=None,
            nrows=preview_rows,
        )
        previews[sheet_name] = raw
        summary_rows.append(
            {
                "sheet_name": sheet_name,
                "preview_rows": len(raw),
                "preview_columns": raw.shape[1],
                "non_empty_preview_cells": int(raw.notna().sum().sum()),
            }
        )

    return pd.DataFrame(summary_rows), previews


def parse_quarter_label(value: object) -> pd.Period | pd.NaT:
    """Parse labels such as 'Sep 2025' or 'Sep-25' as quarterly periods."""
    if value is None or pd.isna(value):
        return pd.NaT

    text = str(value).strip()
    if not QUARTER_PATTERN.match(text):
        return pd.NaT

    parsed = pd.to_datetime(text.replace("-", " "), errors="coerce")
    if pd.isna(parsed):
        return pd.NaT

    return parsed.to_period("Q")


def coerce_published_number(series: pd.Series) -> pd.Series:
    """
    Convert published values to numeric.

    Hyphens, empty text and common suppression labels become missing
    values, never zero.
    """
    cleaned = (
        series.astype("string")
        .str.strip()
        .replace(
            {
                "": pd.NA,
                "-": pd.NA,
                "–": pd.NA,
                "—": pd.NA,
                "n.p.": pd.NA,
                "np": pd.NA,
            }
        )
        .str.replace("$", "", regex=False)
        .str.replace(",", "", regex=False)
    )
    return pd.to_numeric(cleaned, errors="coerce")


def find_quarter_columns(columns: pd.Index) -> list[object]:
    """Return column labels that look like published quarter labels."""
    return [
        column
        for column in columns
        if not pd.isna(parse_quarter_label(column))
    ]


def melt_quarter_matrix(
    table: pd.DataFrame,
    *,
    area_column: str,
    property_type: str,
    value_name: str = "median_weekly_rent",
) -> pd.DataFrame:
    """
    Convert a wide area-by-quarter matrix to a tidy panel.

    Use only after visually confirming the workbook header row and the
    meaning of the selected values.
    """
    if area_column not in table.columns:
        raise KeyError(f"Area column not found: {area_column!r}")

    quarter_columns = find_quarter_columns(table.columns)
    if not quarter_columns:
        raise ValueError("No quarter-like columns were found.")

    tidy = table[[area_column, *quarter_columns]].melt(
        id_vars=area_column,
        var_name="quarter_label",
        value_name=value_name,
    )

    tidy = tidy.rename(columns={area_column: "rental_area_name"})
    tidy["rental_area_name"] = (
        tidy["rental_area_name"].astype("string").str.strip()
    )
    tidy["quarter"] = tidy["quarter_label"].map(parse_quarter_label)
    tidy[value_name] = coerce_published_number(tidy[value_name])
    tidy["property_type"] = property_type

    tidy = tidy.dropna(subset=["rental_area_name", "quarter"])
    return tidy[
        [
            "rental_area_name",
            "quarter",
            "property_type",
            value_name,
        ]
    ].reset_index(drop=True)


def validate_rent_panel(
    frame: pd.DataFrame,
    *,
    value_column: str = "median_weekly_rent",
) -> None:
    """Raise useful errors when the rental panel breaks its data contract."""
    required = {
        "rental_area_name",
        "quarter",
        "property_type",
        value_column,
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    key = ["rental_area_name", "quarter", "property_type"]
    duplicates = frame.duplicated(key, keep=False)
    if duplicates.any():
        examples = frame.loc[duplicates, key].head(10).to_dict("records")
        raise ValueError(f"Duplicate rental-panel keys found: {examples}")

    non_missing = frame[value_column].dropna()
    if (non_missing < 0).any():
        raise ValueError(f"{value_column} contains negative values.")
