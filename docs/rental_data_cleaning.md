# Rental data cleaning — HomeReach Melbourne

## Source and output

- Source file: `quarterly-median-rents-local-government-area-september-quarter-2025-excel.xlsx`
- Source SHA-256: `b8e96347494f09fea2a2ace55997fd34c9398f8509cb3450d65444aebfaaa837`
- Publisher: https://www.dffh.vic.gov.au/publications/rental-report
- Source worksheet: `2br Flat`; published property label: `2 bedroom flats`.
- Source reporting snapshot: `2025Q3`.
- Generated UTC: 2026-10-03T16:50:32.037678+00:00
- Output: `data/processed/rent_quarterly.parquet` and `rent_quarterly.csv`.
- Quality manifest: `data/processed/rent_quality_report.json`.

## Analytical grain and coverage

One row = one source-labelled LGA x one quarter x one property category.
Key: `rental_area_name`, `quarter`, `property_type`.
The output has 3,286 rows and 14 columns: 31 LGAs x 106 quarters, 1999Q2–2025Q3.
The metropolitan subset uses the publisher's North and West Metro (14),
Eastern Metro (7), and Southern Metro (10) groups. Totals are excluded.

## Transformation

1. Read the source without editing it; verify its audited fingerprint and headers.
2. Forward-fill regional metadata only and retain original LGA names.
3. Select individual LGAs in the three source metropolitan groups.
4. Build one 31-row table for each validated Count/Median quarter pair.
5. Stack all quarter tables, convert measures explicitly and add real quarter-end dates.
6. Retain source row, count-cell and rent-cell references; sort by LGA, category and date.
7. Validate keys, coverage, types, missingness, all source values and file read-back.

## Data dictionary

| Column | Meaning |
|---|---|
| rental_area_name | Original LGA label; not a suburb or address. |
| source_region | Source metropolitan group label. |
| area_type | LGA. |
| property_type | Original label: 2 bedroom flats. |
| quarter | Observation quarter, stored as YYYYQn. |
| quarter_end | Calendar quarter-end date. |
| published_count | Source Count measure, stored as a nullable integer; not available stock. |
| median_weekly_rent | Source Median, in AUD per week. |
| source_file | Original workbook filename, without a local personal path. |
| source_sheet | 2br Flat. |
| source_reporting_quarter | Workbook publication snapshot: 2025Q3. |
| source_excel_row | One-based original worksheet row. |
| source_count_cell | Original Count cell address. |
| source_median_cell | Original Median cell address. |

## Validation outcome

- Duplicate keys: 0.
- Missing count values: 0.
- Missing rent values: 0.
- Numeric values checked against original cells: 6572.
- Every LGA has 106 consecutive quarters in the selected snapshot.
- CSV and Parquet read-back match the in-memory table.
- Original workbook fingerprint unchanged.

## Limitations and deferred work

These are area-level historical published statistics from a September 2025 snapshot,
not live listings, vacancies or current prices. Count is retained under its original
measure name; consult the publisher's definitions before further interpretation.
Do not obtain the metropolitan median by averaging LGA medians.
Missing source markers would stay missing; no rent or count values were imputed.
Names such as Mornington Penin'a are preserved for a later reviewed geography crosswalk.
Source grouping and geographic vintages still need review when joining boundary data.
Historical values in this snapshot are not proof of identical real-time historical vintages.
No transport join, rent-growth feature, forecast, inflation adjustment or dashboard replacement
has been performed. The demo app still uses synthetic data until deliberately connected.
