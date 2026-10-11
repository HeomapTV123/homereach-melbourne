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

## Rental EDA and first geographic map

Completed exploratory analysis of the validated rental panel, including
latest-quarter rent comparisons, selected LGA histories, year-on-year
changes and published-count context.

Matched the September 2025 rental observations to the ABS 2025 LGA
boundaries using reviewed names and official LGA codes.

### Verified results

- Rental EDA checkpoint passed.
- Four EDA charts and four analysis tables were exported.
- All 31 selected rental LGAs matched to boundaries.
- 28 names matched exactly.
- Three name translations were explicitly reviewed.
- No unmatched rental LGAs or duplicate LGA codes remained.
- No mapped geometries were missing, empty or invalid.
- Original rental values and source references were preserved.
- Five deliberately incorrect join examples were rejected.
- GeoPackage, GeoJSON and CSV read-back checks passed.
- The map rendered successfully in VS Code.
- Original input files remained unchanged.

### Interpretation limits

The map describes published median weekly rents for two-bedroom flats
in 2025Q3 using ABS 2025 statistical boundaries. It is not a live-listing
map, an individual-property valuation, or a suitability recommendation.

## Reusable geography pipeline

Moved the reviewed geographic matching and validation logic into a
reusable Python module and command-line script. The three reviewed
name translations are stored in a separate configuration CSV.

### Local verification

The complete automated test suite passed: 125 tests, with no skips.

The read-only geography check matched all four existing notebook
exports and wrote no files.

The full geography build matched all 31 rental LGAs to their reviewed
ABS boundary codes. There were no unmatched areas, duplicate codes,
or missing or invalid mapped geometries.

All 14 original rental fields and the native boundary shapes were
preserved. GeoPackage, GeoJSON and CSV save-and-read-back checks
passed.

The boundaries record in the data registry was updated. Original
input files, notebooks and the existing HTML map remained unchanged.

### Reproduction commands

    python -m pytest -o "addopts=" -q
    python scripts/build_lga_geography.py --check-only
    python scripts/build_lga_geography.py --update-registry

### Scope

This implementation is validated for the audited ABS 2025 boundary
snapshot and the selected 2025Q3 two-bedroom-flat rental observations.
A different source snapshot requires review rather than bypassing
the fingerprint checks.

### Next milestone

Audit an official public-transport schedule snapshot, identify the
relevant feeds and service dates, and prepare transport stops for
geographic matching.