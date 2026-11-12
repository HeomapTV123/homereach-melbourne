# HomeReach Melbourne — Fixed final rental-forecast evaluation

Execution started (UTC): 2026-11-11T10:38:07.850809+00:00

## Pre-scoring protocol and scope

- Frozen protocol commit: `d0858bdf46fa6b15c34731f0e41873fb5a2ccfe9`.
- Execution HEAD: `2919a4efa3cb0322b6d307f3b5be2d8df5258655`.
- Protocol SHA-256 (canonical JSON): `f0168e345aafba1a64b883bef1fe351185d7cf57575ce870f252301b484d1495`.
- Saved notebook source SHA-256: `cc28178d9974d370bf5fecd3c5c279ee3e3f8e826148b17b964d60d6c57160e9`.
- Final targets: 2023Q4–2025Q3; 31 source-group LGAs; two-bedroom flats; nominal AUD/week.
- Primary comparison: the fixed damped-change candidate versus last observation. Other methods are secondary references, not post-hoc replacements.
- All four methods have exactly 248 forecasts. Validation and final scores are kept separate.

## Final-period metrics

| Method | Role | Targets | MAE (AUD/week) | RMSE (AUD/week) | Mean signed error (forecast - actual) |
|---|---|---:|---:|---:|---:|
| Last observation | primary_reference | 248 | 13.6089 | 19.4388 | -7.9234 |
| Half-adjusted change Ridge | primary_candidate | 248 | 13.1493 | 18.3265 | -5.2421 |
| Earlier level Ridge | secondary_reference_only | 248 | 13.7226 | 18.6964 | -5.7817 |
| Seasonal naive | secondary_reference_only | 248 | 40.6411 | 47.1694 | -39.8750 |

## Primary paired comparison

The fixed correction candidate has lower pooled MAE than last observation on the reserved later period.
- Candidate minus last-observation MAE: -0.459531 AUD/week (negative favours candidate).
- Relative MAE improvement: 3.3767%.
- Lower candidate MAE in 21 LGAs; lower last-observation MAE in 10; numerical ties in 0.
- Numerical tie tolerance: 1e-09 AUD/week. This is not a practical-importance threshold.
- Descriptive error differences only. No significance test, iid confidence interval, prediction interval or automatic deployment rule.
- The final outcomes must not be used to retune features, alpha, damping, training window or per-LGA model choices.

## Fixed rolling procedure

For target t, every method uses only this LGA/property history dated at or before t-1. Predictions are formed before target actuals are attached.
The two trained methods refit StandardScaler and Ridge at every origin on 94–101 earlier supervised examples. First training target: 2000Q2. Alpha=1, intercept enabled, SVD solver.
Level Ridge uses four rent lags and target-quarter indicators. The correction model uses three lagged changes and target-quarter indicators; forecast = last rent + 0.5 × predicted change.
Earlier final-period outcomes enter only later origins, following the committed one-step procedure. No model setting is selected using final errors.
Last observation copies t-1; seasonal naive copies t-4. Both are one-quarter-ahead forecasts. No clipping, rounding, deadband or outcome-direction oracle.
Finite negative predictions retained and flagged: 0. Nonfinite predictions or missing targets stop the evaluation.

## Verification

- 2,356 prior validation comparison rows verified; earlier metrics and files preserved.
- 1,178 prior baseline predictions independently matched to historical values.
- 97,712 historical lag comparisons and 73,284 historical-change checks across final origins.
- 496 baseline copied-value/quarter/cell checks; 992 final-target lag/source-cell records.
- 496 training-only scaler and independent mathematical Ridge prediction checks; 3,224 feature/coefficient records.
- Exact target coverage, per-LGA/per-quarter metric denominators, pooled RMSE and paired-loss contributions reconciled.
- 21 fictional self-check groups; these are notebook checks, not added pytest cases.
- 13 CSV tables reloaded and matched; 4 final-period charts.
- Original rental files, previous experiments, application, registry and packaged release unchanged.

## Interpretation boundaries

- Single 2025Q3 workbook vintage; historical publication lags and revisions not reconstructed. Period-based retrospective evaluation, not a real-time backtest.
- Final outcomes appeared in prior descriptive EDA and the explorer. Reserved from modelling evaluation, not a pristine blind test.
- Candidate designed after inspecting validation errors; the validation advantage is development evidence.
- Published nominal medians cover changing lettings, not a fixed property or inflation-adjusted series.
- Eight final quarters are a limited later-period check, not proof of performance at all future dates.
- The candidate was designed after validation diagnostics. Final-period errors are a limited later-period assessment, not a new tuning opportunity.
- MAE is error in an area-level weekly-rent statistic. It is not a weekly forecast of individual property prices or a live/current-rent forecast.
- A favourable numeric result alone does not justify online model promotion. The deployed explorer remains descriptive.
- Identical reruns only verify saved evidence. A bug fix must preserve and document the original attempt and outcome exposure; it is not a fresh unseen test.

## Reproduction

Run notebooks/13_rental_final_evaluation.ipynb on feat/rental-forecast-baselines after the committed protocol check.
Outputs: data/interim/rental_final_evaluation/. Existing complete results are compared and preserved, not silently overwritten.
If a previous/partial run conflicts with the code or input lineage, stop, preserve it and document the issue before another evaluation.
Runtime: {"numpy": "2.3.5", "pandas": "3.0.3", "plotly": "7.1.0", "python": "3.12.14", "scikit_learn": "1.8.0"}

## Primary references

- https://otexts.com/fpp3/tscv.html
- https://scikit-learn.org/stable/modules/cross_validation.html
- https://scikit-learn.org/stable/common_pitfalls.html
- https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html
- https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.StandardScaler.html
