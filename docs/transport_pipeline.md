# Reusable transport pipeline — HomeReach Melbourne

## Purpose and scope

This update moves the already-validated computations from notebooks **06 and 07**
into ordinary Python modules and one terminal command. It does not execute or
parse notebooks at runtime. Notebook 05 remains the evidence for the original
full selected-feed audit; this command does **not** pretend to repeat every
inactive-trip, shape, transfer or pathway audit.

The implementation is intentionally bound to the audited `gtfs.zip`, its exact
SHA-256, feeds **2, 3 and 4**, **2026-10-13 Australia/Melbourne** service-day time,
and the same **31 reviewed ABS-2025 LGA associations**. Changing the source or
method requires an audit and a reviewed implementation update, not changing a
hash merely to make a check pass. There is no arbitrary `--date` or `--force` flag.

Rental data remains **2025Q3**. This newer timetable must not be used as evidence
of historical transport availability in rental-model backtests.

## Files added (nine)

| File | Role |
|---|---|
| `config/gtfs_snapshot.json` | Audited source/date, feed scope, counts and policy contract |
| `src/homereach/transport/__init__.py` | Package marker; no import side effects |
| `src/homereach/transport/gtfs.py` | ZIP reading, identifier/date validation, calendar exceptions and active trips |
| `src/homereach/transport/spatial.py` | Stop preparation, strict spatial assignment, independent checks and boundary diagnostic |
| `src/homereach/transport/service.py` | Active stop-time scanning, terminal/pickup/window rules and reconciled summaries |
| `src/homereach/transport/pipeline.py` | Input verification, comparison, staged export and optional registry update |
| `scripts/build_transport.py` | Command-line entry point |
| `tests/test_transport.py` | 116 synthetic pytest cases; no real archive/network requirement |
| `docs/transport_pipeline.md` | This guide |

Copy the five top-level folders (`config`, `src`, `scripts`, `tests`, `docs`)
into the existing HomeReach root and **merge** them. Do not replace or delete the
project folder. These files are additions; they do not replace notebooks 01–07,
existing modules, the Streamlit app, workflow, or environment definitions.

## Commands — use Anaconda Prompt

```bat
cd /d "D:\My project\homereach_melbourne"
conda activate homereach
python -c "import sys; print(sys.executable)"
python -m pytest -o "addopts=" -q
```

With the previously completed 125 cases and the 116 new cases, the expected
result in the full `homereach` environment is **241 passed**. A skipped test is
not a pass. Use `-rs` to see a skip reason; do not remove tests to obtain green.

Read-only project check:

```bat
python scripts/build_transport.py --check-only
```

Full build and optional update of **only the GTFS registry record**:

```bat
python scripts/build_transport.py --update-registry
```

Full build without changing the registry:

```bat
python scripts/build_transport.py
```

`--check-only` and `--update-registry` are mutually exclusive. The read-only
check still performs the spatial work and three stop-time scans, then compares
existing output values. It writes **no project outputs or registry changes**;
large compressed inner ZIPs may spool to operating-system temporary storage,
which is automatically cleaned up.

Each command independently rebuilds the results. Do not run both simultaneously,
rerun notebooks, resave source files, or edit reference outputs during a build.
Changes to tracked inputs/reference files cause a stop before publishing outputs.

## What the command does

1. Verify the pinned transport contract and raw ZIP.
2. Verify the upstream geography build and its output fingerprints. Check the
   native 31 polygons against the actual, pinned ABS ZIP, and rebuild the reviewed
   name/code crosswalk from the supplied alias configuration.
3. Read the smaller selected-feed tables. Preserve identifiers as text and use
   `(feed_id, raw_id)` namespaces; cross-feed matching strings are not deduplicated.
4. Rebuild the stop/platform selection and strict spatial assignment. Verify each
   point independently against the 31 polygons and preserve original source fields.
5. Select active trips using weekly calendars **and date exceptions**.
6. Read all 11,847,183 stop-time rows in chunks, retaining only active-trip records
   for one feed at a time. Process **complete** active trips before applying any
   LGA/time/pickup filtering.
7. Reconcile event partitions, trip memberships, stop totals, LGA totals and
   independent network-level distinct-trip totals.
8. Compare all rebuilt CSV values/schema/order and point GeoPackage attributes/
   coordinates with available notebook exports **before writing anything**.
9. Compare any existing pipeline outputs too. A different output causes failure,
   not silent overwrite or a forced reconciliation.
10. For a full build, stage 17 CSV tables and one point GeoPackage, read them back,
    compare, then publish each file. Write the pipeline report last.
11. With `--update-registry`, back up and update the GTFS row after a successful
    export; preserve other datasets, custom fields and notes.

The build is offline. Optional PROJ grid downloads are disabled during the run;
the caller's prior network setting is restored afterward.

## Policy preserved from the notebooks

- Blank `location_type` means stop/platform (`0`). Hierarchy records remain in a
  separate table rather than being counted as boarding locations.
- Only a unique strict-interior point/polygon match receives an LGA code. Outside,
  exact-boundary, ambiguous and invalid-coordinate records are not forced into
  the closest area. The audited file yields 21,426 inside and 3,605 outside records.
- The 10 m proximity flag is diagnostic, not an accuracy guarantee, catchment
  analysis or reassignment rule. All 443 flags are retained.
- Calendar additions/removals override weekly calendars; exception-only services
  are supported by the selection helper.
- Explicit `route_short_name == Replacement Bus` (case-insensitive) remains a
  separate category. Feed 2 alone does not establish that a service is rail.
- A counted event is regular pickup (`0`, including blank), has a later sequence
  in its complete trip, and has a reviewed `matched_within` LGA assignment.
- Exclusion audit categories are exhaustive and **exclusive**: terminal first,
  then no-pickup, arrangement-required, unassigned location, otherwise counted.
- The final sequence is found BEFORE geographic/time filtering. No consecutive
  sequence numbering is assumed. Duplicate numeric sequence keys are rejected.
- Full-service-day totals retain 24:00+ times. Morning is `[07:00, 09:00)`.
  Times are not reduced modulo 24; adjacent service days are not combined.
- A trip may visit several stops and several LGAs. Event counts are additive
  across the disjoint assignments; LGA distinct-trip totals are **not** additive
  for network trip totals. Network trips are deduplicated independently.
- All 31 × 4 × 2 = 248 LGA/category/window combinations remain, including zeroes.
- Frequency-based or flexible/continuous-service extensions are not implemented;
  the audited snapshot reader rejects their unreviewed presence.

No walking access, downstream alighting/transfer feasibility, headways, actual
punctuality, vehicle counts, passenger counts or transport score is calculated.
Area size, route arrangement and stop placement affect raw LGA totals.

## Outputs: notebook evidence stays untouched

Notebook-produced inputs/results remain under:

```text
data/interim/gtfs_audit/
data/interim/gtfs_spatial/
data/interim/gtfs_service/
```

The refactored pipeline uses a **new output directory**:

```text
data/processed/transport/
├── spatial/
│   ├── stop_lga_matches.csv
│   ├── stop_lga_matches.gpkg
│   ├── location_selection_counts.csv
│   ├── excluded_location_records.csv
│   ├── spatial_candidates.csv
│   ├── spatial_match_summary.csv
│   ├── unassigned_stops.csv
│   ├── near_boundary_review.csv
│   └── stop_records_by_lga_and_feed.csv
├── service/
│   ├── active_trip_lookup.csv
│   ├── trip_stop_scope.csv
│   ├── lga_service_indicators.csv
│   ├── stop_service_indicators.csv
│   ├── trip_lga_memberships.csv
│   ├── feed_service_summary.csv
│   ├── event_filter_audit.csv
│   ├── scan_summary.csv
│   └── event_trace_examples.csv
└── transport_pipeline_report.json
```

The main downstream analytical table is now:

`data/processed/transport/service/lga_service_indicators.csv`

The two sets are intentionally separate: interim files are notebook evidence;
processed files are the reproducible pipeline outputs. Data values match, not
necessarily GeoPackage bytes, generation timestamps or package-version metadata.
No manually edited prose in the notebook reports is replaced.

Existing reference files are compared individually. On your completed project,
expect **18/18** notebook files matched: 17 CSVs plus the GeoPackage. Absent
reference files are explicitly reported as absent, not called compared. A fresh
checkout can build from the raw ZIP and completed geography pipeline even when
notebook outputs are unavailable; the pinned GTFS snapshot reuses its recorded
audit contract without claiming to have run all of notebook 05 again.

## Registry behaviour

Only `dataset_id=gtfs` changes. Its status becomes `service_indicators_validated`.
Fields identify the source filename/fingerprint, service date, timezone, selected
feeds, explicit processed scope, output path and build command. No download date,
licence or release date is invented. Other rows and custom notes remain.

Before updating, the original CSV is saved under
`data/interim/registry_backups/`. A changed/malformed registry stops the build.
No registry changes occur without `--update-registry`.

## First full-build checkpoint

```text
Notebook exports matched: 18/18
Previous pipeline exports matched: 0/18
Data registry: GTFS row updated; other dataset records preserved
TRANSPORT PIPELINE CHECKPOINT PASSED
Service date: 2026-10-13 (Australia/Melbourne)
Stop/platform records: 25031 | Within selected LGAs: 21426 | Outside retained: 3605
Source stop-time rows scanned: 11847183
Active trip records: 35580
Active stop-time rows: 1311746
Counted service-day departure events: 1175281
Counted AM departure events: 158932
Distinct AM trip records across the study area: 5768
LGA/category/window rows: 248
Independent spatial and count checks: passed
17 CSV tables and point GeoPackage read-back: matched
Original sources, notebook outputs and earlier reports: unchanged
Saved: data/processed/transport/transport_pipeline_report.json
```

`Previous pipeline exports matched: 0/18` is normal on the first build: the new
processed directory does not yet exist. After a successful build, expect 18/18
on a repeat build/check. A read-only check prints `TRANSPORT CHECK-ONLY PASSED`
and `Project outputs written: 0` instead of the export read-back result.

## Failure handling and limitations of file transactions

Do not edit fingerprints or delete outputs to make a failed comparison pass.
First inspect the reported mismatch, especially changed code, source ZIPs,
coordinate operation choices or unsaved notebook edits.

Files are staged and validated before replacement. Individual replacements are
atomic, but publishing multiple files and the registry is **not** a database
transaction. The report is published last. Do not use simultaneous writers; a
crash or locked-file error may require reviewing the output directory and rerunning
with the same unchanged sources. Never present a partially written build as complete.

The default chunk size is 100,000 input rows. It limits raw CSV reads but does NOT
strictly limit total memory to 100,000 rows: complete active-trip records for one
feed are retained to detect terminals before filtering. This matches the successful
notebook method. `--chunk-rows` changes read granularity, not analytical policy.

## Verification performed during preparation

- Python 3.13.5, pandas 2.2.3, GeoPandas 1.1.2, Shapely 2.1.2.
- **116 new synthetic tests passed**; no new test skips.
- Complete supplied project: **240 passed, 1 skipped**. The skip was the pre-existing
  rental Parquet integration test because this preparation environment lacks
  pyarrow. Your completed 125-test run had no skips; expected local total: 241.
- Reconstructed test inputs from the user's actual uploaded sources, not fictional
  production data. The rental test input was rebuilt with the validated module
  from artifact_tool-read workbook cells; geography used the validated pipeline.
- Executed notebooks 05, 06 and completed 07 in the isolated reference project.
- All 17 pipeline CSV tables matched the notebook values, schemas and ordering.
- Point GeoPackage source coordinates and attributes matched notebook 06.
- Full command exported all tables and GeoPackage, reloaded them, and updated the
  test registry successfully. Reference notebook data and reports stayed unchanged.
- The complete `--check-only` command was rerun after export; all 18 notebook and
  all 18 pipeline outputs matched. Fingerprints for project data, config, docs
  and notebooks were identical before and after that read-only run.
- These checks do not substitute for the user's Windows/pandas-3 local verification.

## Reading the code

Start with `build_active_trips()` in `gtfs.py`, then `assign_points()` in
`spatial.py`, then `classify_active_events()` and `summarize_events()` in
`service.py`. The first three answer: which trips run, where each stored stop
lies, and which stop-time visits meet the counting policy. The orchestrator
handles file checks and publication; it does not alter those analytical rules.

## Next stage

After local tests and both command modes pass, save this code milestone in Git.
Do not force-add raw or processed files. The existing workflow will discover the
new `tests/test_transport.py`. Then explore the completed LGA service indicators
and combine their raw measures with rents while keeping source periods visible.
No new model, weighting system, score, recommendation or app integration is
introduced by this refactor.

## Primary references

- GTFS Schedule definitions: https://gtfs.org/documentation/schedule/reference/
- Publisher: https://opendata.transport.vic.gov.au/dataset/gtfs-schedule
- Spatial join: https://geopandas.org/en/stable/docs/reference/api/geopandas.sjoin.html
- Chunked reading: https://pandas.pydata.org/docs/reference/api/pandas.read_csv.html
- pytest temporary files: https://docs.pytest.org/en/stable/how-to/tmp_path.html
