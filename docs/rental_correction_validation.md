# HomeReach Melbourne — Half-adjusted rent-change Ridge validation

Generated (UTC): 2026-11-09T14:24:05.191268+00:00

## Fixed candidate and timing

This candidate was designed after the earlier level-Ridge validation and diagnostics. Its settings were fixed before its own scores were computed, but validation has already informed development; this is not independent evaluation or preregistration.
Forecast = previous-quarter rent + 0.5 × predicted quarterly rent change. Separate LGA models use the three preceding quarterly changes and known target Q2/Q3/Q4 indicators.
StandardScaler is fitted on the six training-only features at each origin. Ridge alpha=1.0, intercept enabled, SVD solver. Damping=0.5 is a fixed heuristic, not a probability or an optimised value.
No grid search, alpha/weight tuning, per-LGA winner selection, observed-direction oracle, clipping or rounding. Raw predicted changes are audit evidence only, not a separately scored candidate.
Target transformation, feature transformation and damping change together; their individual causal effects are not isolated.
Rolling validation: 2019Q1–2023Q3, 589 equally weighted LGA-quarter targets. Initial history ends 2018Q4; four-lag warm-up yields 75–93 supervised training rows per fit.
Final period 2023Q4–2025Q3 is excluded from features, fitting, predictions, metrics and charts. No transport features or current/future forecast.

## Validation results

| Method | Targets | MAE (AUD/week) | RMSE (AUD/week) | Mean signed error (forecast minus actual) |
|---|---:|---:|---:|---:|
| Last observation | 589 | 10.9728 | 16.2303 | -4.3582 |
| Seasonal naive | 589 | 25.2937 | 38.9464 | -13.0934 |
| Earlier level Ridge | 589 | 13.2135 | 18.6421 | -1.9758 |
| Half-adjusted change Ridge | 589 | 10.9133 | 15.4055 | -2.7078 |

Candidate MAE change relative to last observation: -0.54% (negative is better).
Lower candidate MAE in 16 LGAs; lower last-observation MAE in 15; numerical ties: 0.
The fixed candidate improved pooled validation MAE over last observation. This remains inspected-development-set evidence, not final-period or prospective confirmation.
A smaller signed bias does not imply smaller absolute error. Positive and negative errors can cancel. Error comparisons share areas/time; no iid interval, p-value or significance claim is made.
Negative candidate rent predictions: 0; no clipping was used.

## Verification and evidence

- 18 fictional self-check groups passed, including future mutation, target-outcome removal, constant histories and translation invariance.
- 11,656 lag values/quarters/source cells and 8,742 lag-change values independently checked.
- 1,178 baseline forecasts checked against the underlying source history; all 1,767 saved predictions retained unchanged.
- 589 candidate fits and raw/final predictions verified against an independent closed-form Ridge solution.
- Training scaler means, variances and sample counts checked per fit. No target/future outcome joins into training.
- 2,356 forecast source-lag records and 3,534 six-feature scaling/coefficient records exported.
- 2,356 scored comparison rows: four methods × the same 589 validation targets.
- Previous overall, per-LGA and per-quarter metrics matched; pooled metrics independently reconciled.
- Nine CSV round trips passed; four validation-only interactive charts saved.
- No previous notebook output, input data, configuration, app, registry or frozen release file overwritten.

## Research limitations and next gate

The experiment uses one 2025Q3 workbook vintage. Historical publication lags and revisions are not reconstructed. This is not a real-time backtest.
The reserved period appeared in previous descriptive EDA and the live historical explorer; it is not a pristine unseen test. It remains unscored in the research experiments so far.
The 2019Q1–2023Q3 period has informed multiple modelling decisions. Do not present improvement here as independent confirmation or keep searching until a method wins.
Record this fixed candidate, then review whether to freeze a single selection rule before a separately controlled final-period evaluation. No automatic model promotion or app update occurs.
Published medians are not individual-property prices; nominal changes are not inflation-adjusted. The half correction does not guarantee improvement on flat or declining targets.

## Reproduction

Run notebooks/12_rental_correction_validation.ipynb on feat/rental-forecast-baselines after notebooks 09–11.
Research output folder: data/interim/rental_correction_validation/. This generated report is replaced on an identical rerun; keep personal notes elsewhere.
Protocol SHA-256: 16f85a6c887eb12fb623c59259592791f620aa4a2c635f156fac9f5f080f6542.
Runtime: Python 3.12.14, pandas 3.0.3, scikit-learn 1.8.0.

## Primary references

- https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html
- https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.StandardScaler.html
- https://scikit-learn.org/stable/common_pitfalls.html
- https://otexts.com/fpp3/tscv.html
