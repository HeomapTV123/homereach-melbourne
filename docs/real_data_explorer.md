# HomeReach Melbourne — Real-data explorer

## Purpose and scope

This additive update takes the verified comparison logic from notebook 08 into
ordinary Python functions, builds an application-ready local bundle, and provides
a separate Streamlit entry point. The original `app/Home.py` synthetic scoring demo
is deliberately unchanged. The real-data explorer never imports synthetic input
rows, environment scores, commute estimates or forecasts.

The explorer is descriptive, not a recommendation service. It compares the
published **2025Q3 two-bedroom-flat rents** with the **13 October 2026** selected
GTFS service snapshot. The AM window is 07:00 inclusive to 09:00 exclusive in
Australia/Melbourne. ABS 2025 identifiers and statistical polygons cover the same
31 source-group metropolitan LGAs as before. This does not become a contemporaneous
housing/transport dataset merely because its records are joined.

## Files added

- `app/Explore.py`: separate real-data entry point.
- `scripts/build_explorer_data.py`: read, validate, derive, compare and export.
- `src/homereach/explorer/__init__.py`: package declaration.
- `src/homereach/explorer/analysis.py`: reusable notebook-08 combination logic.
- `src/homereach/explorer/bundle.py`: file integrity, export and app loading.
- `src/homereach/explorer/charts.py`: scatter, history, categories and map figures.
- `src/homereach/explorer/ui.py`: four pages and descriptive controls.
- `tests/test_explorer.py`: 57 data/filter/figure checks using synthetic examples.
- `tests/test_explorer_ui.py`: 10 actual Streamlit AppTest cases with fictional data.
- `docs/real_data_explorer.md`: this guide.

There are no replacements for existing application code, configuration,
requirements, workflows, notebooks or registry records. Merge the folders into the
existing project. Do not put the files inside an additional nested project folder.

## Required existing work

The rental, geography and transport pipelines must have completed. Notebook 08's
six CSVs and its manifest are used as read-only comparison evidence when present.
The new builder reads processed outputs, not notebook variables and not raw GTFS.
It does not regenerate or alter earlier pipeline reports. The validated rental CSV
is sufficient: no new Parquet export or spreadsheet operation occurs in this update.

Existing project dependencies are used. The interface uses Streamlit >= 1.50
(`width="stretch"`, `st.Page`, `st.navigation`) and Plotly's map API >= 5.24, already
used by notebook 04. The user's logged Streamlit version is newer; do not recreate
Conda or upgrade unrelated libraries just to install this update. The app reports
an actionable error if the installed Streamlit version is too old.

## First run (Anaconda Prompt / CMD)

```bat
cd /d "D:\My project\homereach_melbourne"
conda activate homereach
python -m pytest -o "addopts=" -q
python scripts/build_explorer_data.py --check-only
python scripts/build_explorer_data.py
python -m streamlit run app/Explore.py --server.port 8502
```

The 241 existing cases + 57 data/chart cases + 10 UI cases give **308 expected
passing tests in the complete project environment**. A skipped case is not a pass.
Use `python -m pytest -o "addopts=" -q -rs` to inspect any skips or failures.
Stop at a failure rather than disabling the test or bypassing a fingerprint check.

Port 8502 keeps this entry point separate from a synthetic demo running on 8501.
Open the Local URL printed by Streamlit, normally `http://localhost:8502`.
Keep its terminal open. Do not execute terminal commands as notebook cells.
For other work, open another terminal instead of restarting the whole environment.

PowerShell alternative: use `Set-Location "D:\My project\homereach_melbourne"`
instead of `cd /d`; Conda activation must already be available in that shell.

## Builder checkpoints

First read-only run, when notebook 08 is complete and no explorer bundle exists:

```text
Notebook 08 tables matched: 6/6
Previous explorer data files matched: 0/9
EXPLORER CHECK-ONLY PASSED
Comparison LGAs: 31 | Rental history rows: 3286 | Service-category rows: 248
Rent: 2025Q3 | Transport: 2026-10-13 | Boundaries: 2025
AM events: 158932 | Distinct study-area AM trips: 5768
Input files, notebooks, registry and synthetic demo: unchanged
Raw GTFS scans: 0
Project outputs written: 0
```

The first full build also reports 0/9 **before creating its first outputs**. Its
final checkpoint instead reads:

```text
Eight CSV tables and the GeoJSON reloaded and matched.
EXPLORER DATA CHECKPOINT PASSED
Comparison LGAs: 31 | Rental history rows: 3286 | Service-category rows: 248
Rent: 2025Q3 | Transport: 2026-10-13 | Boundaries: 2025
AM events: 158932 | Distinct study-area AM trips: 5768
Input files, notebooks, registry and synthetic demo: unchanged
Raw GTFS scans: 0
Saved: data/processed/explorer/explorer_manifest.json
```

After the first successful build, an unchanged repeat check should match 9/9
previous data files. Absent notebook references are explicitly reported, never
called compared. Existing differing data files stop the build; there is no
force-overwrite flag. Staging/reloading occurs before publication; individual
replacements are not a multi-file database transaction. Do not run two builders
or notebook exporters simultaneously. A partial build is rejected by app hashes.

## Application bundle

Only `data/processed/explorer/` is written:

```text
am_lga_category_comparison.csv       124 AM category rows
lga_transport_comparison.csv         31 transport rows
rent_transport_comparison.csv        31 rows, the same 43 fields as notebook 08
am_stop_denominator_comparison.csv   31 denominator rows
study_area_reconciliation.csv        2 time-window rows
source_periods.csv                   3 source-period rows
rental_history.csv                  3,286 rent rows with reviewed 2025 identifiers
lga_service_categories.csv           248 LGA/category/window rows
lga_boundaries_2025.geojson           31 polygons in WGS84
explorer_manifest.json              lineage, schemas, hashes and validation
```

The first six tables are compared with notebook 08. The rental-history table adds
identifiers only: it contains no 2026 transport features. Attaching 2025 identifiers
to older published names does not establish historically constant boundaries.
The map displays **2025Q3 only**, not a historical boundary animation.

Native geometry is checked against the reviewed code/name inventory and transformed
to WGS84 on a copy. No clipping, simplification, repair or re-assignment occurs.
The resulting GeoJSON uses only geometry and identifiers; displayed rent values
come from the same comparison table shown elsewhere in the app.

The app checks the bundle's file hashes and the current upstream pipeline reports
before loading. A changed upstream report requires rebuilding the bundle rather
than mixing new inputs with old displayed results. The data cache key includes
verified file content. Cache use never silently falls back to synthetic data.
This is a local prototype, not a deployment package with standalone data hosting.

## Four pages

### Compare LGAs

All 31 areas appear alphabetically by default. Optional controls filter by the
source's regional groups, an **area-median rent ceiling**, and minimum distinct AM
trips in an LGA. A median ceiling is not evidence of available properties under that
budget and is not an income-based affordability test. Empty filters produce an
explanation rather than a crash. Sorts are descriptive, not a combined ranking.

The CSV download contains only the displayed areas, with all source-period fields
and analytical fields retained. The scatter shows 2025Q3 rent on the x-axis and
2026-10-13 AM trips on the y-axis. No regression, score or causal claim is added.

The two price metrics are the minimum and maximum **displayed LGA medians**. They
are not metropolitan medians; no average of medians is presented as a city result.

### Area details

Choose an LGA, view its rent history (5 years, 10 years or all quarters), download
that history and inspect its four service categories for AM or the complete GTFS
service day. Labelled replacement buses remain explicitly visible even at zero.
A source-evidence expander lists the original workbook, worksheet and Excel cells.

The historical line is nominal, not inflation-adjusted, and represents different
new-letting mixes over time. It does not track a fixed dwelling's individual rent.
Published counts do not measure live listings or vacant properties.

### Rental map

Map all 31 LGAs by 2025Q3 median rent. The default white background makes no
external tile requests; the online background is explicit opt-in. Plotly uses
browser WebGL. A readable table fallback is available when the map fails to render.
All geometry and original rental information stay separate from synthetic scores.

### Data and methodology

See source periods, counting rules, source references, limitations and the build
manifest. The correct study-area AM distinct-trip total is 5,768; adding LGA counts
produces 12,546 and is explicitly identified as the wrong network total. A stop can
serve residents in another LGA; no residential catchment, walking, capacity,
reliability, waiting-time or destination-specific journey analysis has been made.

## Manual acceptance check on the user's machine

1. Open `app/Explore.py` through Streamlit on port 8502. Confirm real LGA names,
   separate dates, 31 displayed areas, no Demo Area A/F and no overall score.
2. Enable the published-rent ceiling and set it below $400. Confirm the explanatory
   empty result. Disable the ceiling and confirm all 31 areas return.
3. Select Melbourne on Area details. Confirm $730/week, 1,633 distinct AM trips,
   and that changing the service window updates the category chart/table.
4. Inspect Monash and Whitehorse: both have $600/week in the selected rental
   snapshot. The source cells match the earlier audited examples.
5. Open Rental map and check coloured polygons and hover details. White space is
   not a zero-rent measurement. Test online tiles only when network use is desired.
6. Download a filtered comparison CSV and confirm both dates remain in it.

## Validation performed while preparing this update

Preparation environment: Python 3.13.5, pandas 2.2.3. The official uploaded rental
workbook values were read with artifact_tool, transformed by the established rental
module and checked against all source cells. The boundary and transport inputs were
rebuilt with the supplied established pipelines in an isolated project copy.

- Actual-source new builder completed; 6/6 reference notebook-08 tables matched.
- All 8 CSV exports reloaded exactly; GeoJSON round trip and 31 features verified.
- Repeat read-only build matched 9/9 new data files with no writes.
- 57 new data/filter/figure tests passed.
- Complete available suite: **297 passed, 2 skipped**. One skip is the existing
  rental Parquet case (pyarrow unavailable); one is the entire new UI module
  (Streamlit unavailable). The UI module contains 10 intended cases, none claimed
  as executed here. These dependencies are already in the user's complete environment.
- Comparison scatter and rental-history figures rendered in a browser. The browser
  could not initialise WebGL for the map; map geometry and figure configuration were
  checked, but interactive map appearance must be verified locally.
- The live Streamlit server was NOT launched here. Download/install access for the
  missing package was unavailable. The four-page interaction tests and manual UI
  checks are an explicit user-side checkpoint, not reported as already passing.

No skipped case is reported as passed. Synthetic fixtures belong only to tests;
they are not a fallback data source for the application.

## Git checkpoint after tests/build/UI verification

Do not commit raw or generated data or rewrite existing commits. Suggested stages:

```bat
git add app/Explore.py scripts/build_explorer_data.py
git add src/homereach/explorer/__init__.py src/homereach/explorer/analysis.py src/homereach/explorer/bundle.py
git add src/homereach/explorer/charts.py src/homereach/explorer/ui.py
git add tests/test_explorer.py tests/test_explorer_ui.py docs/real_data_explorer.md
git --no-pager diff --cached --stat
git commit -m "feat: add verified real-data HomeReach explorer"
git push
```

Do not stage `data/processed/explorer` with `-f`. No Git operation is performed by
the builder or app. No automation, scheduling or background refresh is added.

## Primary technical references

- Streamlit navigation: https://docs.streamlit.io/develop/concepts/multipage-apps/overview
- Streamlit plot width: https://docs.streamlit.io/develop/api-reference/charts/st.plotly_chart
- Streamlit tests: https://docs.streamlit.io/develop/api-reference/app-testing
- pandas merges: https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.merge.html
- GeoPandas projections: https://geopandas.org/en/stable/docs/user_guide/projections.html
- DFFH rental definitions: https://www.dffh.vic.gov.au/publications/rental-report
- GTFS fields: https://gtfs.org/documentation/schedule/reference/
