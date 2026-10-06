# Week 2 — Reusable rental pipeline

## Purpose

Replace the need to rerun eleven notebook cells with a reproducible command.
The analytical method and the 14-column output remain the same as in
`notebooks/02_clean_rental_data.ipynb`.

This adds files to the existing project. It does not replace either notebook,
`src/homereach/io/rent.py`, the Streamlit demo, existing tests, the project charter,
`config/project.yml` or your environment definition.

## Files added

| Path | Role |
|---|---|
| `config/rent_snapshot.json` | Reviewed filename, fingerprint, sheet, category and expected coverage |
| `src/homereach/io/dffh_rent.py` | Reusable reading, cleaning, validation, export and registry functions |
| `scripts/build_rent_panel.py` | Command-line entry point |
| `tests/test_dffh_rent.py` | 50 synthetic test cases, with no official workbook or network dependency |
| `docs/rental_pipeline.md` | This guide |

The dedicated `rent_snapshot.json` supplies the paths and source contract for
this pipeline. It deliberately does not use the older placeholder rental filename
in `config/project.yml`. Do not change the fingerprint simply to make a check pass.
A different workbook needs its own audit and reviewed configuration.

## Copying into the project

Extract the update into a temporary folder. Copy its five folders (`config`,
`docs`, `scripts`, `src`, `tests`) into:

```text
D:\My project\homereach_melbourne
```

Merge the folders; do not delete or replace the project directory. There should
be exactly one extra file inside each matching destination folder, except that
the module belongs inside `src/homereach/io/`. Keep the raw XLSX in
`data/raw/rent/` with the original filename. No Conda environment recreation is
required. The local project was already installed in editable mode.

## Run from Anaconda Prompt

```bat
cd /d "D:\My project\homereach_melbourne"
conda activate homereach
python -m pytest -o "addopts=" -q
```

With the six original tests and the new 50 test cases, the normal result in the
fully installed environment is **56 passed**. A skipped test is not a pass:
use `python -m pytest -o "addopts=" -q -rs` to see why any case was skipped.
The Parquet integration case explicitly skips when `pyarrow` is unavailable.
Your completed cleaning notebook has already exercised Parquet in `homereach`.

Then:

```bat
python scripts/build_rent_panel.py --update-registry
```

Do not paste the command into a notebook code cell. These are terminal commands.
Do not run both the notebook exporter and this script simultaneously.

## What the command does

1. Read the exact snapshot specification and verify the workbook fingerprint.
2. Read `2br Flat` with the same settings used in the notebook.
3. Select the publisher's three metropolitan groups and exclude all totals.
4. Rebuild Count/Median pairs and stack the quarters into the 14-column table.
5. Validate unique keys, dates, complete coverage, types and source values.
6. Compare any existing CSV and Parquet exports with the newly rebuilt table.
   A mismatch stops the command before replacing the exports; it is not ignored.
7. Write staged CSV and Parquet files, reload and validate them, then replace
   the derived exports and the quality JSON. Individual replacements are not
   a multi-file database transaction; do not use simultaneous writers.
8. With `--update-registry`, update the `rent` record only after the build succeeds.

Expected core output:

```text
Previous exports: matched (rent_quarterly.csv, rent_quarterly.parquet)
CSV and Parquet read-back: matched
Data registry: rent row updated; other dataset records preserved
PIPELINE CHECKPOINT PASSED
Rows: 3286
Columns: 14
Metro LGAs: 31
Quarters: 106 (1999Q2 to 2025Q3)
Duplicate keys: 0
Missing count values: 0
Missing rent values: 0
Source numeric values verified: 6572
Original workbook unchanged: True
```

On a fresh checkout with no derived exports, the earlier-exports message instead
says `not present; first build`. That is not the same as comparing old exports.

## Outputs and changes

The script rebuilds these existing derived files:

- `data/processed/rent_quarterly.csv`
- `data/processed/rent_quarterly.parquet`
- `data/processed/rent_quality_report.json`

The data values must match the notebook exports. Quality-report generation times
change on reruns; binary Parquet bytes can also depend on library versions.
Reproducibility here means the validated values/schema, not an identical timestamp.

`--update-registry` edits `docs/data_registry.csv`. It preserves existing custom
columns, notes, source descriptions and all other dataset records. New provenance
columns are appended; the other datasets have blanks in those new columns.
A copy of the pre-update registry is retained under
`data/interim/registry_backups/`, keyed by its file fingerprint.

The rental status becomes `cleaned_validated`. Its `processed_scope` explicitly
limits this to the 31 selected source-group metropolitan LGAs and `2 bedroom flats`.
Other worksheets have not been cleaned by this script. Download dates and licence
claims are NOT invented. Reporting quarter is not a file-acquisition date.

The source XLSX and all existing notebook/report/charter text remain unchanged.
There are no network requests, Git commands or changes to the running Streamlit app.

## Inspect the source code in this order

Start with `build_panel()` inside `src/homereach/io/dffh_rent.py`.
Its main inputs are `raw` (the worksheet as a DataFrame) and `spec` (the reviewed
configuration). Its output is `panel` (the clean table). It does not use notebook
global variables or write files.

Next read `validate_panel()`. It independently checks the resulting table,
including every source row and column coordinate, not just the total number of
records. A changed median, a Count column accidentally used as a Median, a missing
quarter or an aggregate pretending to be an LGA must cause a failure.

Finally read the small `main()` function in `scripts/build_rent_panel.py`, which
calls the functions in order. The command-line `--update-registry` switch is parsed
with Python's `argparse` library.

The module's helper `require()` uses explicit exceptions so checks remain active
even when Python optimizations disable ordinary `assert` statements. Tests still
use pytest's normal assertions to report expected versus actual results.

## Why synthetic tests are appropriate

Tests contain fictional areas such as Fixture A, Fixture B and Fixture C with
known counts and rents. There are deliberately malformed variants. These are
software test inputs, not a replacement for the official rental dataset.

Cases include invalid dates, reordered measures, duplicate keys, damaged source
references, missing and negative measurements, fractional counts, altered source
fingerprints, exact CSV read-back, registry-note preservation, and repeatable
Parquet/CSV export. Temporary test files stay in pytest's temporary directory.

Thus GitHub Actions can test the code without uploading the original workbook.
The existing workflow already runs pytest; no workflow edit is needed. This does
not mean CI has validated the official workbook on GitHub: that full-source check
runs locally through the build command.

## Validation performed while preparing this update

- Python 3.13.5 / pandas 2.2.3 in the preparation environment.
- 49 new synthetic cases passed; one Parquet export integration case was skipped
  because `pyarrow` was unavailable in that environment.
- Together with the six original starter tests: **55 passed, 1 skipped**.
- The actual uploaded worksheet was inspected with artifact_tool, then its values
  were fed to the new transformation and to the existing notebook implementation.
  All 3,286 rows and 14 columns matched exactly.
- All 6,572 numeric source comparisons passed.
- The command-line reader and `--check-only` validation ran on the actual XLSX.
- The actual-data CSV read-back and previous-notebook-CSV comparison passed.
- The full Parquet export/registry-writing command has NOT been end-to-end verified
  in the preparation environment; run the tests and full command in `homereach`
  to verify that final path. Your environment already has the Parquet dependency.

No test is reported as passed merely because it was skipped.

## Useful commands

Validate without changing files or checking old CSV/Parquet exports:

```bat
python scripts/build_rent_panel.py --check-only
```

Rebuild data without editing the registry:

```bat
python scripts/build_rent_panel.py
```

Show command help:

```bat
python scripts/build_rent_panel.py --help
```

On `No module named homereach`, check the active environment and project folder,
then run `python -m pip install -e .` from the project root. Do not create a new
Conda environment or uninstall unrelated packages.

A fingerprint mismatch means the workbook must be rechecked, not edited to fit.
A previous-export mismatch means the refactor and old result differ; stop and
inspect before changing data. A locked-file error on Windows usually requires
closing that derived CSV or registry file in Excel before rerunning.

## Save the milestone after local checks pass

Save both notebooks first so their outputs are retained. Review `git status` and
`git diff -- docs/data_registry.csv`. Then stage the specific new files and updated
registry, rather than forcing raw or processed data into version control:

```bat
git add config/rent_snapshot.json src/homereach/io/dffh_rent.py scripts/build_rent_panel.py tests/test_dffh_rent.py docs/rental_pipeline.md docs/data_registry.csv
git add notebooks/01_data_audit.ipynb notebooks/02_clean_rental_data.ipynb docs/rental_workbook_audit.md docs/rental_data_cleaning.md
git diff --cached --stat
git commit -m "feat: add tested reproducible rental data pipeline"
git push
```

Do not force-add `data/raw/` or `data/processed/`. Do not mark a future forecast,
transport join or deployment as completed. A code/test pass is not a housing-market
finding and does not validate a predictive model.

## Next milestone

After the tests and build command pass locally, update the Week 2 progress record
and begin exploratory rental analysis. Geographic mapping follows the rental EDA.
Do not change the Streamlit demonstration to real recommendations yet.

## Technical references

- Python modules: https://docs.python.org/3/tutorial/modules.html
- Command-line arguments: https://docs.python.org/3/library/argparse.html
- pandas Excel loading: https://pandas.pydata.org/docs/reference/api/pandas.read_excel.html
- pandas comparisons: https://pandas.pydata.org/docs/reference/api/pandas.testing.assert_frame_equal.html
- pytest parametrization: https://docs.pytest.org/en/stable/how-to/parametrize.html
- pytest temporary files: https://docs.pytest.org/en/stable/how-to/tmp_path.html
- Source page: https://www.dffh.vic.gov.au/publications/rental-report
