# HomeReach Melbourne — Rental Forecast Model Card

**Status:** first modelling round completed; reusable implementation verified.
Research branch: `feat/rental-forecast-baselines`. This card describes the
research recorded through refactor commit `cc46371` on 11 November 2026.

## Purpose and intended use

The research asks how accurately the next quarter's published median weekly
rent for two-bedroom flats can be predicted from earlier observations of the
same rental-source LGA. Its intended use is a reproducible student research
and portfolio demonstration of chronological evaluation, baseline comparison,
data lineage and automated verification.

The deployed HomeReach application provides descriptive rental and transport
comparisons. These forecasts have not been released as an application feature.
The results do not support individual-property pricing, current-rent estimates,
household affordability decisions or area recommendations. See the
[modelling summary](rental_modelling_summary.md) and
[deployed release record](releases/first-deployed-explorer.md).

## Data and prediction target

| Item | Recorded scope |
|---|---|
| Source | Homes Victoria / DFFH September-quarter-2025 LGA rental workbook; worksheet `2br Flat` |
| Geography | 31 LGAs in the source's North and West Metro, Eastern Metro and Southern Metro groups; original labels retained |
| Property category | `2 bedroom flats` |
| History | 1999Q2–2025Q3: 106 quarters and 3,286 LGA-quarter observations |
| Target | `median_weekly_rent`, nominal AUD per week |
| Prediction unit | One `(rental_area_name, property_type, target_quarter)` |
| Horizon | One calendar quarter ahead, with forecast origin at `target_quarter - 1` |

The audited file is
`quarterly-median-rents-local-government-area-september-quarter-2025-excel.xlsx`.
The [source snapshot](../config/rent_snapshot.json) pins its fingerprint and
scope. The [rental pipeline](rental_pipeline.md) preserves published counts and
source-cell references alongside rents. Counts are source information, not
model inputs or metric weights.

## Chronological evaluation design

| Stage | Quarters | Coverage |
|---|---|---|
| Initial observed history | 1999Q2–2018Q4 | 79 observations per LGA before the first validation target |
| Development validation | 2019Q1–2023Q3 | 19 targets per LGA; 589 forecasts per method |
| Final modelling evaluation | 2023Q4–2025Q3 | Eight targets per LGA; 248 forecasts per method |

For target quarter `t`, each model accesses only the same LGA/property history
through `t-1`. The trained methods fit a fresh scaler and estimator at every
origin using all eligible earlier supervised examples, with no cross-LGA pooling.
Predictions are constructed before target outcomes are joined for scoring.

The first four source quarters provide lag warm-up; supervised training targets
begin at 2000Q2. Training contains 75–93 examples per fit during validation and
94–101 during final evaluation, above the minimum of 40. An earlier final-period
outcome can enter history at a later origin under this repeated one-step
procedure. Final errors cannot change the fixed model settings.

Development errors informed the candidate. The final protocol was committed
before final scoring, but final-period observations had appeared in descriptive
EDA and the explorer. This is a retrospective evaluation with disclosed prior
outcome exposure, not a pristine blind test. Sources:
[development findings](rental_correction_validation.md),
[frozen protocol](../config/rental_final_evaluation_protocol.json) and
[final evaluation](rental_final_evaluation.md).

## Four fixed methods

| Display name | Saved method identifier | Final-evaluation role | Forecast rule |
|---|---|---|---|
| Last observation | `last_observation` | Primary reference | Copy the same series' rent at `t-1` |
| Half-adjusted change Ridge | `damped_change_ridge_alpha1_weight05` | Primary candidate | Last rent plus `0.5 × predicted quarterly change` |
| Earlier level Ridge | `ridge_lags_seasonal_alpha1` | Secondary reference | Predict the rent level from historical lags and calendar indicators |
| Seasonal naive | `seasonal_naive` | Secondary reference | Copy rent at `t-4`; forecast origin remains `t-1` |

**Level Ridge:** features are `rent_lag_1` through `rent_lag_4`, plus known
target-quarter indicators `target_is_q2`, `target_is_q3` and `target_is_q4`.
Q1 is the reference quarter; the training target is rent at `t`.

**Change Ridge:** features are the three preceding changes,
`rent(t-1)-rent(t-2)`, `rent(t-2)-rent(t-3)` and `rent(t-3)-rent(t-4)`, plus the
same quarter indicators. The training target is `rent(t)-rent(t-1)`; the final
forecast is `rent(t-1) + 0.5 × predicted_change(t)`.

Both Ridge methods use `alpha=1.0`, an intercept and the SVD solver. A separate
`StandardScaler` centres and scales every feature using training rows only at
each origin. Damping `0.5` is a fixed heuristic, not an estimated probability
or an optimised weight. Raw predicted changes are audit values rather than
an additional scored method.

The implementation uses no count, transport or geographic predictors, parameter
search, per-LGA winner selection, clipping or rounding. Finite negative
predictions are retained and flagged; the recorded final run had none. Missing
history, duplicate keys, invalid rents or nonfinite predictions stop evaluation.
The reusable API also rejects missing or blank historical source metadata.
Sources: [forecast construction](../src/homereach/forecasting/core.py),
[evaluation](../src/homereach/forecasting/evaluation.py) and
[refactor checks](forecasting_refactor.md).

## Results and interpretation

MAE is primary; RMSE and mean signed error are secondary. Signed error is
`forecast - actual`, so a negative mean indicates average underprediction.
Every LGA-quarter has equal weight. Pooled RMSE uses individual squared errors,
not the average of LGA RMSEs. Values below are nominal AUD/week, rounded for display.

### Development validation: 2019Q1–2023Q3

Each method has 589 targets. These results informed development and are kept
separate from the later final period.

| Method | MAE | RMSE | Mean signed error |
|---|---:|---:|---:|
| Last observation | 10.9728 | 16.2303 | -4.3582 |
| Half-adjusted change Ridge | 10.9133 | 15.4055 | -2.7078 |
| Earlier level Ridge | 13.2135 | 18.6421 | -1.9758 |
| Seasonal naive | 25.2937 | 38.9464 | -13.0934 |

The candidate reduced validation MAE by about AUD 0.0595/week, or 0.54%.
The earlier level Ridge performed worse than last observation; that result is
retained. Sources: [baselines](rental_forecast_baselines.md),
[level Ridge](rental_ridge_validation.md) and
[candidate validation](rental_correction_validation.md).

### Final evaluation: 2023Q4–2025Q3

Each method has 248 targets, giving 992 forecast rows across the four methods.

| Method | MAE | RMSE | Mean signed error |
|---|---:|---:|---:|
| Last observation | 13.6089 | 19.4388 | -7.9234 |
| Half-adjusted change Ridge | 13.1493 | 18.3265 | -5.2421 |
| Earlier level Ridge | 13.7226 | 18.6964 | -5.7817 |
| Seasonal naive | 40.6411 | 47.1694 | -39.8750 |

The prespecified primary comparison is change Ridge versus last observation.
Candidate-minus-reference MAE is **-0.459531 AUD/week**, a **3.3767%** relative
MAE reduction calculated from unrounded errors. Candidate MAE is lower in
**21 LGAs** and higher in **10**, with no numerical ties. The numeric tie
tolerance is `1e-9` AUD/week.

This modest, mixed reduction in historical forecast error is not a rent saving,
an accuracy percentage or a guaranteed future improvement. No practical-importance
threshold, significance test, confidence interval, prediction interval or
automatic deployment rule was established. Source:
[final evaluation and paired comparison](rental_final_evaluation.md).

## Verification and recorded checkpoint

Notebook 13 preserves source-quarter and workbook-cell lineage, training/scaler
audits, independent mathematical Ridge checks, grouped metric reconciliation and
CSV read-back checks. Its 21 fictional self-check groups are distinct from the
later pytest cases. See the [original verification record](rental_final_evaluation.md)
and [regression-test guide](forecasting_refactor.md).

The maintainer's local Windows run on 11 November 2026 verified the refactor
against the original saved evidence before committing it:

| Check | Observed result |
|---|---|
| Complete pytest suite | **490 passed in 105.05 seconds**; 352 existing cases plus 138 new cases |
| Saved notebook table comparison | **13/13 matched** |
| Final forecast rows compared | **992** |
| Trained fits reproduced | **496** |
| Project files written by the verifier | **0** |
| Additional independent final tests | **0**; replay checks implementation equivalence |

This is a local verification record. The [CI workflow](../.github/workflows/ci.yml)
at `cc46371` triggers on pushes to `main` and pull requests targeting `main`.
The direct research-branch push did not trigger a CI run for that commit.

## Provenance

| Record | Commit |
|---|---|
| Protocol fixed before final scoring | `d0858bdf46fa6b15c34731f0e41873fb5a2ccfe9` |
| Original final-evaluation execution | `2919a4efa3cb0322b6d307f3b5be2d8df5258655` |
| Executed notebook and narrative report recorded | `dce9b7b8d929e8cb0601c1104dc3adb314ee357b` |
| Reusable implementation and regression tests committed and pushed | `cc46371fe16310ce24150cb85a07b27dac3df656` |

The maintainer ran the comparison while HEAD was `dce9b7b`, then committed the
checked files as `cc46371`. The original execution identifier remains intact.
Canonical final-protocol SHA-256:
`f0168e345aafba1a64b883bef1fe351185d7cf57575ce870f252301b484d1495`.
The [final report](rental_final_evaluation.md) records the original runtime:
Python 3.12.14, pandas 3.0.3, NumPy 2.3.5 and scikit-learn 1.8.0.

## Checking completed evidence

From the existing project in **Anaconda Prompt / Command Prompt**, with Git and
the development environment available:

```bat
conda activate homereach
cd /d "D:\My project\homereach_melbourne"
git branch --show-current
python -m pytest -o "addopts=" -q
python scripts/verify_rental_forecast_refactor.py --check-only
```

The branch must be `feat/rental-forecast-baselines`. Tests use fictional data;
the equivalence command requires the validated rental CSV and quality report,
completed notebook 09–12 evidence, and original notebook 13 results under
`data/interim/rental_final_evaluation/`. These outputs are Git-ignored, so a
fresh clone alone cannot run the saved-evidence comparison.

The command imports [reusable functions](../src/homereach/forecasting/__init__.py)
and compares all 13 tables with exact identifiers, counts and text and float
tolerances `rtol=1e-10`, `atol=1e-9`. It checks protocol and file fingerprints
and has no export mode. Existing results can be checked directly without
rerunning notebooks. Preserve a failure and investigate its cause; do not alter
reference hashes or results to make the check pass. Details:
[read-only verifier](../scripts/verify_rental_forecast_refactor.py) and
[equivalence requirements](forecasting_refactor.md).

## Limitations and release decision

- One 2025Q3 workbook vintage is available. Historical publication delays and
  revisions were not reconstructed, so this is a period-based retrospective
  evaluation rather than a real-time backtest.
- Published nominal medians describe changing collections of lettings. They
  neither track a fixed property nor adjust for inflation; historical LGA
  boundary changes were not independently harmonised.
- Development diagnostics informed the candidate, and final-period observations
  appeared in earlier descriptive work. Final errors must not be used for tuning
  and then presented as another unseen evaluation.
- Eight final quarters provide limited evidence. Errors share areas, histories
  and time periods; independence and statistical significance are not claimed.
- Target transformation, feature transformation and damping changed together.
  This experiment does not isolate their individual causal contributions.

The completed research supports retaining and documenting the fixed candidate's
modest average error reduction alongside its limitations. The deployed explorer
remains descriptive. Future model changes require disclosed development and
additional independent evidence; a production forecast proposal needs a separate
review of current data, performance, intended use and uncertainty.
