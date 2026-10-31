# HomeReach Melbourne — Rental forecast baselines

Generated (UTC): 2026-10-31T18:46:52.356849+00:00

## Target and fixed protocol

Retrospective one-quarter-ahead forecasts of published nominal median weekly rent for two-bedroom flats, separately for 31 rental-source metropolitan LGAs.
No transport, current-quarter published counts, or future rental values are predictors. Both baselines have horizon one quarter.
Initial history: 1999Q2–2018Q4 (79 quarters). Rolling validation: 2019Q1–2023Q3 (19 targets per LGA).
Reserved final evaluation: 2023Q4–2025Q3 (8 quarters; 248 LGA-quarter outcomes). No predictions or error scores for that period are created here.
These dates were specified in config/rental_forecast_protocol.json before error calculation; they are project choices, not official publisher labels.

## Validation results

| Method | Validation targets | MAE (AUD/week) | RMSE (AUD/week) | Mean signed error (forecast − actual) |
|---|---:|---:|---:|---:|
| Last observation | 589 | 10.9728 | 16.2303 | -4.3582 |
| Seasonal naive | 589 | 25.2937 | 38.9464 | -13.0934 |

MAE is the primary metric. Every LGA-quarter has equal weight; errors are not weighted by published counts. A positive signed error is over-prediction.
Pooled RMSE is calculated from all squared errors, not by averaging per-area RMSEs. These correlated historical errors have no claimed confidence interval or significance test.

## Method

For target t, last observation copies t−1 and seasonal naive copies t−4 for the same area/category. Origin is t−1 for both.
At each later validation origin, previously observed validation outcomes enter the available history. This is repeated one-step evaluation, not a fixed-origin multi-step forecast.
Predictions are constructed before actual outcomes are attached; source quarter and original workbook cell are retained for every forecast.

## Verification

- Rental input: data\processed\rent_quarterly.csv; SHA-256 4020fe247cf704ab01a40dc546e7b460cbe58a3fcb1ad00eb3b947dac80dbb18.
- Original source workbook SHA-256: b8e96347494f09fea2a2ace55997fd34c9398f8509cb3450d65444aebfaaa837.
- Protocol SHA-256: ac96b5cdae0341a108764a0d38f9e6d2e4dcb8c4ebc4efbeff679d6f133f5d83.
- 589 validation forecasts per method; 1,178 prediction rows and independent value/quarter/cell matches.
- Twelve synthetic self-check groups passed; these are notebook checks, not new pytest cases.
- Pooled, per-LGA and per-quarter counts reconciled; six CSV tables reloaded and matched.
- Four interactive charts contain validation data only; 0 final-holdout forecasts and 0 current/future published forecasts.
- Protected inputs, application and frozen release were not changed.

## Interpretation limits

Only one 2025Q3 workbook vintage is available. Historical release lags and revisions are not reconstructed; this is NOT a real-time backtest.
The recent holdout outcomes have already appeared in prior descriptive EDA and the explorer. They are reserved from modelling evaluation here, not a pristine blind test.
The full source CSV is read for structural checks; its holdout outcomes are excluded before model construction and from metrics/charts/prediction exports.
Source-area labels follow the publisher's historical series; this does not independently harmonise historic administrative-boundary changes.
Published medians describe changing sets of lettings; this is not an individual-property forecast, inflation-adjusted series, live-rent estimate or area recommendation.
No out-of-sample uncertainty intervals, causal claims, fitted ML model or deployment recommendation are produced. Keep the final period reserved until model choices are fixed.

## Reproduction

Run notebooks/09_rental_forecast_baselines.ipynb on feat/rental-forecast-baselines with the existing homereach kernel.
Research outputs are under data/interim/rental_forecast_baselines; this report is regenerated on rerun. Keep personal notes separately.

## Primary references

- https://otexts.com/fpp3/simple-methods.html
- https://otexts.com/fpp3/tscv.html
- https://otexts.com/fpp3/accuracy.html
- https://www.dffh.vic.gov.au/publications/rental-report
