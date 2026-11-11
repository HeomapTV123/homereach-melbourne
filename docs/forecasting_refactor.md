# HomeReach — fixed forecasting refactor and equivalence checks

## Purpose

Turn notebook 13's verified forecast construction, audit tables and metrics into
importable functions and automated regression tests. This is an engineering
refactor of an already-scored final evaluation, **not another independent test**,
a new model, a first-time evaluation, or a deployment decision.

The final protocol is unchanged: lock commit
`d0858bdf46fa6b15c34731f0e41873fb5a2ccfe9`, canonical JSON SHA-256
`f0168e345aafba1a64b883bef1fe351185d7cf57575ce870f252301b484d1495`.
The reference notebook source SHA-256 is
`cc28178d9974d370bf5fecd3c5c279ee3e3f8e826148b17b964d60d6c57160e9`.
Outputs, execution counts and notebook metadata are not part of that source hash.
This package was reviewed against research-branch commit
`dce9b7b8d929e8cb0601c1104dc3adb314ee357b`, which records the completed notebook
and final report.

## Files and responsibilities

| File | Responsibility |
|---|---|
| `src/homereach/forecasting/core.py` | History-only inputs; fixed scalers and estimators; source lineage; metrics and paired losses |
| `src/homereach/forecasting/evaluation.py` | Generate the same 13 in-memory table contracts as notebook 13 |
| `src/homereach/forecasting/equivalence.py` | Validate the committed protocol and completed local evidence, compare tables, detect file changes |
| `src/homereach/forecasting/__init__.py` | Export the reusable functions; not imported by the live application |
| `scripts/verify_rental_forecast_refactor.py` | Read-only command with no export or tuning option |
| `tests/test_forecasting.py` | 97 fictional-data regression tests |
| `tests/test_forecast_equivalence.py` | 41 file, comparison, Git-gate and orchestration tests |
| `docs/forecasting_refactor.md` | This implementation guide |
| `docs/rental_modelling_summary.md` | Consolidated retrospective research interpretation |

All nine files are additions. No existing file, protocol, notebook, environment,
CI workflow, registry or deployment payload is replaced. Development stays on
`feat/rental-forecast-baselines`; do not merge to `main` during this checkpoint.

## What is reused, and what is not

The public forecast functions reproduce the four fixed methods: last observation,
seasonal naive, level Ridge (alpha 1), and change Ridge (alpha 1) with a fixed 0.5
adjustment to the last rent. Both trained methods use a fresh training-only
StandardScaler and the SVD Ridge solver at each origin. No cross-LGA pooling,
current/future outcome predictors, count/transport features, clipping, rounding,
parameter search or per-area winner selection are added.

Notebook code is not executed or dynamically extracted by the new command. The
notebook is read as JSON solely to verify its already-recorded source fingerprint.
Functions live in normal Python modules with explicit inputs and known table
contracts. The existing read-only protocol verifier is compared against its lock
commit before its verification function is imported.

The core helper can receive small fictional histories/origins for tests. The
production CLI accepts **no date, model, alpha, feature or damping overrides** and
checks the complete pinned specification before recomputation.

## Prerequisites

The local completed notebook 13 outputs must already exist at:

```
data/interim/rental_final_evaluation/
```

The command also requires the local validated rental CSV and quality report,
earlier experiment manifests/outputs (09–12), the locally generated final report,
the original notebook source, reviewed protocol files and the Git lock history.
It does not fetch missing data, reconstruct missing evidence or consult the raw
GTFS archive. A fresh clone without these local research outputs is intentionally
not sufficient. The independent unit tests do not require those outputs.

## Run locally

From Anaconda Prompt:

```bat
cd /d "D:\My project\homereach_melbourne"
conda activate homereach
python -m pytest -o "addopts=" -q
python scripts/verify_rental_forecast_refactor.py --check-only
```

The new tests add 138 collected cases to the previously confirmed 352. With the
complete dependencies, the project installed (`python -m pip install -e .`) and
Git available, expect **490 passed**. The path-escape
unit test simulates resolved-path traversal without requiring Windows symlink
privileges. Git integration tests can skip if Git is absent. Review any skip
rather than equating it to a pass. All application code remains outside the
new forecasting package.

`--check-only` is optional: the command is always read-only. There is no full-build
mode and no new final-results directory. No need to rerun notebooks 09–13 first.
Avoid saving notebooks or running another writer during the fingerprint check.

Expected terminal checkpoint:

```text
FORECAST REFACTOR EQUIVALENCE CHECKPOINT PASSED
Original protocol lock: d0858bd
Original final execution: 2919a4e
Refactor execution HEAD: ...
Notebook 13 CSV tables matched: 13/13
Final forecasts compared: 992 | Trained fits reproduced: 496
Historical lag checks: 97712 | Change checks: 73284
Baseline source checks: 496 | Forecast source records: 992
Model settings, final targets and numeric comparison rules: unchanged
Prior evidence, original reports, notebooks and deployed release: unchanged
Project files written: 0 | Additional independent final tests: 0
No model selection, live predictions, model pickle or deployment performed.
```

The current execution HEAD can change when this refactor is committed. It must
not replace the historical execution commit in the original final manifest.

## Equivalence requirements

All 13 original CSV tables are required, including predictions, metrics, primary
paired errors, origin plan, fit/scaler evidence, coefficients and workbook-cell
lineage. Rounded four-decimal error summaries alone cannot establish equivalence.

Identifiers, integer counts and text are checked exactly after sorting by the
full declared key. Column order/schema, row counts, key uniqueness and missing
value locations are checked. Floating-point comparisons use `rtol=1e-10` and
`atol=1e-9` (the original CSV round-trip tolerances); they are not model-selection
thresholds. Original files must also match their existing byte fingerprints.

The original final manifest, protocol copy, narrative report, original notebook
source and earlier experiment fingerprints are validated before computation.
The current source CSV must match both the rental pipeline report and the final
execution manifest. This checks recorded integrity/lineage, not authenticity
against an actor replacing both data and manifests.

The command fingerprints protected source/configuration/docs/notebooks, earlier
research output directories and the published release before and after the run,
including on failure. It excludes Python bytecode caches; the CLI also disables
bytecode writes. There is no raw rental-workbook scan, GTFS scan or network call.

## Regression tests

Fictional examples verify constant histories, exact lag directions, half-change
arithmetic, finite negative predictions, source-cell validity, calendar encoding,
training-only scaling, row-order invariance, area/property isolation, current and
future outcome mutation/removal, metric weighting and zero-denominator behaviour.

File/Git tests use temporary directories and a synthetic local Git history. They
test the original committed gate, wrong branches, changed protocols, altered
files, unsafe paths, text/numeric mismatches and preservation on errors. The
orchestration test uses a deliberately isolated adapter; a full local comparison
against the user's real saved evidence remains a separate required checkpoint.

## Input validation corrections in this package

Review of the earlier refactor found two gaps in the public reusable functions.
Pandas reductions could skip a missing historical source filename, worksheet or
cell reference. A uniformly blank source filename or worksheet could also pass
the uniqueness check. The history builder now explicitly rejects missing or
blank provenance within the selected past rows. Target and future metadata are
still excluded from prediction.

The scoring join previously accepted zero or negative actual rents when they
were finite. The last evaluated quarter could therefore bypass the validation
applied when earlier outcomes became training history. Actual rents must now
be positive; finite negative **predictions** remain retained and flagged as the
frozen protocol requires.

These changes add ten regression cases: nine demonstrate the invalid-input
failures in the earlier implementation, and one protects the history-only
information boundary. The strict official CSV loader already checked positive
rents and pinned source metadata/fingerprints. These are reusable-API fixes;
they do not change the valid recorded forecasts, protocol, or original notebook.

## Verification performed during preparation

- The complete suite passed: **490 passed, no skips**, in 27.26 seconds. This
  comprises the original 352 cases and 138 forecasting/equivalence cases. The
  runtime emitted one unrelated pytest-plugin deprecation warning.
- Verified under Python 3.12.14, pandas 2.2.3, NumPy 2.3.5, scikit-learn 1.8.0
  and pytest 9.2.0, with the project installed in editable mode and the existing
  Streamlit/Parquet/geography test dependencies available. The initial complete
  run exposed a missing editable install in the temporary environment; installing
  the project resolved it without changing application code.
- Before applying the input-validation fixes, nine new invalid-input cases
  failed as expected and the future-metadata isolation case passed. All ten pass
  after the fixes; the existing negative-prediction case also passes.
- Verified the notebook source and workbook fingerprints, rebuilt the 3,286-row
  panel, and validated all 6,572 published source values. Ran only the original
  calculation cells in a separate namespace, never the notebook export code.
- After the final code edits, **13/13** refactored tables matched the reconstructed
  original calculations: 992 forecasts, 496 trained fits, 97,712 historical lag
  checks, 73,284 change checks, 496 baseline checks, 992 lineage records and 3,224
  coefficient records. The last comparison took 10.82 seconds.
- The existing committed-protocol verifier passed at `dce9b7b`. On this fresh
  checkout, the production equivalence CLI correctly stopped because the
  original Git-ignored final manifest and CSV evidence were unavailable.
- The reconstructed comparison is not access to the user's local CSV evidence
  or a new final test. The CLI comparison on the user's computer remains the
  separate checkpoint against the originally saved files.

## Failure handling

Do not edit a fingerprint, protocol, comparison tolerance or reference CSV merely
to pass. Preserve the first mismatch and the original evidence. No original
reports, plots or manifests are rewritten by this command. It does not try to
refresh expired or missing historical sources. A real implementation discrepancy
must be diagnosed and documented; correction does not create an unseen test set.

## References

- Scikit-learn Ridge: https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html
- Leakage safeguards: https://scikit-learn.org/stable/common_pitfalls.html
- pytest temporary directories: https://docs.pytest.org/en/stable/how-to/tmp_path.html
- Protocol: [committed plan](rental_final_evaluation_protocol.md)
- Original results: [final evaluation](rental_final_evaluation.md)
