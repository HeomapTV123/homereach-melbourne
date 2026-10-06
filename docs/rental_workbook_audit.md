# Rental workbook audit — HomeReach Melbourne

## Source and purpose

- Source file: `quarterly-median-rents-local-government-area-september-quarter-2025-excel.xlsx`
- Source SHA-256: `b8e96347494f09fea2a2ace55997fd34c9398f8509cb3450d65444aebfaaa837`
- Audited UTC: 2026-10-02T15:17:07.334790+00:00
- Publisher page: https://www.dffh.vic.gov.au/publications/rental-report
- Purpose: source inspection before implementing the cleaning pipeline.
- No Excel source cells were edited.

## Workbook structure

Worksheets: `1br flat`, `2br Flat`, `3br Flat`, `2br House`, `3br House`, `4br House`, `All Properties`.

Selected worksheet: `2br Flat`; category label: `2 bedroom flats` (A2).
Raw selected-sheet shape: 95 rows by 214 columns.
Row 1 is a title, row 2 contains quarters, row 3 contains Count/Median labels,
and records start at row 4. Column A is a regional label; column B is an LGA or total.
The first measure pair is C:D and the final pair is HE:HF.

## Time and geographic coverage

- 106 continuous quarters, June 1999 (1999Q2) through September 2025 (2025Q3).
- 79 individual LGAs in the full worksheet (B4:B95 after excluding aggregates).
- 12 aggregate rows excluded: regional Group Totals, Metro, Non-Metro and Victoria.
- 31 LGAs in the source's three metropolitan groups (rows 57:90, totals excluded).
- Group sizes: North and West Metro 14; Eastern Metro 7; Southern Metro 10.
- Planned tidy panel: 31 LGAs x 106 quarters x 1 category = 3,286 rows.

## Value audit

Across the 79 individual LGAs, each measure has 8,374 cells: 7,237 numeric and
1,137 hyphen markers. The metropolitan subset has 3,286 numeric Count values
and 3,286 numeric Median values, with no blanks or hyphen markers in either.
No negative values or unexpected text markers were found in these measure cells.
These checks are not proof of complete data quality or suitability for forecasting.

## Decisions for the cleaning pipeline

1. Preserve the source file, published category and original LGA labels.
2. Forward-fill regional metadata only; never forward-fill rents or counts.
3. Remove aggregate rows from the LGA panel; retain them separately if needed.
4. Keep Count and Median separate; do not treat counts as currency.
5. Treat '-' as unavailable, not zero; do not infer a suppression threshold here.
6. Use the three exact source metropolitan group labels for the initial subset.
7. Review names such as Mornington Penin'a before later geographic matching.
8. Do not obtain a metropolitan median by averaging the individual LGA medians.
9. A future forecast must respect what was available at each forecast date;
   a current transport snapshot must not be inserted into historical model evaluation.

## Interpretation limits

This is a September 2025 reporting snapshot, not live rental listings or current prices.
The source's metropolitan groups are the analysis boundary for this stage; later ABS
boundary matching must document classification and geographic vintage differences.
The Count field is retained as a published observation-count measure; consult the
publisher's definitions before claiming it measures available stock or vacancy.
Audit completed; no final cleaned panel or predictive model has been created.
