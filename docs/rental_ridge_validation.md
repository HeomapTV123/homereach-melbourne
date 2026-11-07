# HomeReach Melbourne — Fixed Ridge rental validation

Generated (UTC): 2026-11-07T14:47:32.666094+00:00

## Question and fixed design

Compare a trained Ridge model with the two saved baselines for retrospective one-quarter-ahead published median weekly rent.
One separate model per LGA/property series; no cross-LGA pooling. Four rental lags plus Q2/Q3/Q4 calendar indicators (Q1 reference).
All seven predictors are standardized using training examples only. Ridge alpha=1.0, intercept enabled, SVD solver.
One fixed specification was declared before this experiment was scored. No parameter search, transformation, forecast clipping or post-score retuning.
Initial history ends 2018Q4. Four lag warm-up quarters are omitted, so supervised training starts 2000Q2.
For each validation target, training targets end at the preceding quarter. Models and scalers are refitted at every origin.
Rolling validation: 2019Q1–2023Q3. Reserved final evaluation: 2023Q4–2025Q3, with no forecasts or scores produced here.

## Validation results

| Method | Targets | MAE (AUD/week) | RMSE (AUD/week) | Mean signed error (forecast minus actual) |
|---|---:|---:|---:|---:|
| Last observation | 589 | 10.9728 | 16.2303 | -4.3582 |
| Seasonal naive | 589 | 25.2937 | 38.9464 | -13.0934 |
| Ridge (fixed alpha=1) | 589 | 13.2135 | 18.6421 | -1.9758 |

Ridge MAE change versus last observation: +20.42% (negative is better).
LGAs with lower Ridge MAE: 5; lower last-observation MAE: 26; ties: 0.
All LGA-quarter targets receive equal weight. MAE is primary; RMSE is calculated from all squared errors, not averaged area RMSEs.
A smaller mean signed error does not imply lower absolute error. Positive and negative errors can cancel.
This fixed Ridge candidate did NOT improve on the last-observation baseline on pooled validation MAE.
No model-selection winner for deployment, confidence interval or statistical significance claim is made.

## Leakage and reproducibility checks

- 589 separate LGA/origin model fits; 75–93 earlier supervised examples per fit.
- 11,656 development lag values, quarters and source cells independently checked.
- 589 predictions checked against an independent closed-form Ridge calculation.
- 2,356 forecast lag-source records and 4,123 training-scaler/coefficient records exported.
- Every scaler was checked against its actual training mean, variance and sample count.
- 14 synthetic self-check groups passed, including current/future-outcome mutation and prediction without target outcomes.
- The 1,178 baseline predictions were verified against their local manifest and original historical values; baseline metrics matched.
- Same 589 validation targets per method; 1,767 combined scored prediction rows.
- Nine CSV tables reloaded and matched; four validation-only charts saved.
- Negative Ridge predictions: 0; no clipping was applied.
- No raw transport data, forecasting API, test-period score, current-rent forecast or model deployment.

## Interpretation limits

This is a period-based retrospective experiment with one 2025Q3 workbook vintage. Publication delays and historical revisions are not reconstructed.
Recent final-period outcomes appeared in earlier descriptive EDA and the deployed explorer. They are reserved from modelling evaluation now, not a pristine blind test.
The complete rental CSV is checked structurally, but final-period values are removed before predictor construction, fitting, metrics and plots.
Current target-quarter rent is used only for scoring; current or lagged published counts and the 2026 transport snapshot are not predictors.
The original baseline protocol retains its same-series rule; this extension also trains separately within each LGA.
Historic publisher series are not independently harmonised for boundary revisions. Medians concern changing lettings, not fixed-property histories or current listings.
Success of the software checks means the experiment executed as specified; it does not mean the trained model beat the benchmark.
Repeated experiments can overfit the validation set. Record this candidate, including an unfavourable result, before proposing a new specification.

## Evidence and reproduction

Input CSV SHA-256: `4020fe247cf704ab01a40dc546e7b460cbe58a3fcb1ad00eb3b947dac80dbb18`.
Baseline protocol SHA-256: `ac96b5cdae0341a108764a0d38f9e6d2e4dcb8c4ebc4efbeff679d6f133f5d83`.
Ridge protocol SHA-256: `e98c4793b0e3c4f9bdfc0bfad9e54a9e1507fcc3851e49d8f1c21ec2672475e8`.
Runtime: Python 3.12.14; pandas 3.0.3; scikit-learn 1.8.0; NumPy 2.3.5.
Run notebooks/10_rental_ridge_validation.ipynb on feat/rental-forecast-baselines after notebook 09 has passed.
Research outputs: data/interim/rental_ridge_validation/. This generated report is replaced on rerun; keep personal notes separately.
No prior notebooks, baseline exports, source data, registry, source modules or deployed release files are overwritten.

## References

- https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html
- https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.StandardScaler.html
- https://scikit-learn.org/stable/common_pitfalls.html
- https://otexts.com/fpp3/tscv.html
