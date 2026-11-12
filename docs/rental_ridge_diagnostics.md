# HomeReach Melbourne — Fixed Ridge validation error diagnostics

Generated (UTC): 2026-11-08T13:09:01.304107+00:00

## Scope and evidence

Retrospective diagnosis of the saved notebook-10 predictions on 2019Q1–2023Q3: 31 LGAs, 19 quarters, 589 paired targets.
The plan was specified after the overall Ridge score was known. This is development-set analysis, not a fresh independent evaluation.
No models were fitted and no forecasts were replaced. All 589 targets remain in the analysis. Final period 2023Q4–2025Q3 remains unscored.
The full rental history and transport tables were not loaded; existing files were hashed for integrity.
Original source snapshot: b8e96347494f09fea2a2ace55997fd34c9398f8509cb3450d65444aebfaaa837.

## Reconciled scores

| Method | Targets | MAE (AUD/week) | RMSE (AUD/week) | Signed error (forecast minus actual) |
|---|---:|---:|---:|---:|
| last_observation | 589 | 10.9728 | 16.2303 | -4.3582 |
| ridge_lags_seasonal_alpha1 | 589 | 13.2135 | 18.6421 | -1.9758 |
| seasonal_naive | 589 | 25.2937 | 38.9464 | -13.0934 |

Overall paired MAE difference (Ridge minus last observation): **2.240677 AUD/week**.
Ridge has lower error on 213 targets; last observation has lower error on 376; numerical ties: 0.
Ridge has lower per-LGA MAE in 5 LGAs; last observation in 26.

## Retrospective decomposition by observed median change

| Observed change | Targets | Last-observation MAE | Ridge MAE | Contribution to pooled MAE gap |
|---|---:|---:|---:|---:|
| decreased | 145 | 13.4345 | 17.7738 | 1.068264 |
| increased | 296 | 15.2534 | 14.8220 | -0.216789 |
| unchanged | 148 | 0.0000 | 5.5287 | 1.389202 |

Each contribution divides that group’s sum of paired loss differences by all 589 targets. Contributions add to the pooled gap; negatives offset positives.
Unchanged means the published median is unchanged, not every rent or property. Last observation is then exact by construction; Ridge can add error by moving away.
Observed change is only known after the target. Do not turn these retrospective groups into an oracle model-selection rule.

## Time pattern

| Target year | Targets | Last-observation MAE | Ridge MAE | Ridge minus last MAE |
|---|---:|---:|---:|---:|
| 2019 | 124 | 8.0887 | 6.8671 | -1.2216 |
| 2020 | 124 | 11.4919 | 15.3583 | 3.8664 |
| 2021 | 124 | 6.6210 | 9.5510 | 2.9300 |
| 2022 | 124 | 11.9355 | 13.0909 | 1.1554 |
| 2023 | 93 | 18.6452 | 23.8626 | 5.2174 |

2023 contains Q1–Q3 only. All 19 validation quarters remain in evaluation. These are temporal associations, not explanations of their external causes.
Case examples are the ten largest penalties and ten largest savings selected after seeing errors. They are not a representative sample and were not removed.

## Verification

- All 1,767 saved prediction rows checked; 1,178 previous baseline forecasts matched.
- All 589 lag-1 values and source-quarter references matched to notebook-10 feature lineage.
- Overall, per-LGA and per-quarter metrics recalculated and matched to saved scores.
- Contributions by LGA, quarter, year and observed change reconciled to the pooled MAE gap.
- 12 diagnostic self-check groups passed; eight CSV round trips matched and four HTML charts saved.
- No new model fits, changed forecasts, transport inputs, holdout scores or current/future forecasts.
- Protected earlier research, source modules and deployed release remained unchanged.

## Interpretation and next research gate

These diagnostics describe failure patterns but do not identify a causal mechanism. Forecast errors share areas and quarters; no iid confidence interval, p-value or significance claim is made.
Validation has been used repeatedly for development. Keep final-period outcomes out of model choices; they were already visible in earlier descriptive EDA, so they are not a pristine blind test.
One possible controlled follow-up is a model anchored to the last observation with a learned correction. It would need its own fixed specification and can still lose to the baseline. No such candidate is fitted or selected here.
Historical publication lags, revisions and boundary vintages are not reconstructed. No forecasting feature is added to the deployed explorer.

## Reproduction

Run notebooks/11_rental_ridge_error_diagnostics.ipynb on feat/rental-forecast-baselines with the existing homereach kernel.
Requires the completed notebook-09 and notebook-10 outputs. Writes only data/interim/rental_ridge_diagnostics and this generated report.

## References

- https://otexts.com/fpp3/accuracy.html
- https://scikit-learn.org/stable/common_pitfalls.html
- https://plotly.com/python/interactive-html-export/
