# Week 2 Progress — Rental Data Preparation

## Completed work

The official rental workbook was audited before cleaning. The selected
worksheet was "2br Flat", with the published category "2 bedroom flats".

The cleaning process selected the 31 LGAs in the source's metropolitan
groups, excluded aggregate rows, separated Count from Median, and
converted the report-style worksheet into a quarterly analytical table.

The notebook's cleaning and validation logic was then implemented in a
reusable Python module and command-line pipeline.

## Verified results

- Cleaned rows: 3,286
- Columns: 14
- Metropolitan LGAs: 31
- Reporting periods: 106 quarters, from 1999Q2 to 2025Q3
- Duplicate analytical keys: 0
- Missing published counts: 0
- Missing median weekly rents: 0
- Numeric values matched to source cells: 6,572
- Pipeline output matched the existing notebook exports
- CSV and Parquet save-and-read-back checks passed
- Original workbook remained unchanged
- Rental data registry record updated
- Local automated tests: 56 passed

## Reproduction commands

Run from the project root with the homereach environment active:

    python -m pytest -o "addopts=" -q
    python scripts/build_rent_panel.py --update-registry

## Interpretation limits

This is a validated, source-specific rental dataset, not a forecasting
model or a live property-listing service.

The published count is retained separately from median weekly rent.
It must not be described as the number of currently available properties.

## Next work

Explore historical rent patterns and annual changes, document the
findings, and prepare for geographic matching.