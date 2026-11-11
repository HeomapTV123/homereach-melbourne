# HomeReach Melbourne — first rental-modelling round

## Research question and scope

How accurately can the next quarter's published median weekly rent for two-bedroom
flats be predicted from earlier observations of the same rental-source LGA?
This study covers 31 LGAs and one 2025Q3 workbook vintage. It predicts an area-level
nominal statistic, not an individual listing or a fixed property's rent.

The deployed HomeReach explorer remains descriptive. No forecasting model,
forecast values or model-pickled objects have been added to its frozen data.

## Experimental record

| Notebook | Purpose | Result retained |
|---|---|---|
| 09 | Last-observation and seasonal-naive benchmarks | Last observation was the stronger validation baseline |
| 10 | Separate per-LGA level Ridge, four rent lags and quarter indicators | Worse than last observation on validation |
| 11 | Diagnose those saved validation errors | Error penalties concentrated in decreased/unchanged published medians; no forecasts changed |
| 12 | Fixed half-adjusted change Ridge | Very small validation MAE advantage; no weight or alpha search |
| 13 | Fixed later-period evaluation after a committed protocol | Modest lower average error for the correction candidate, not a uniform improvement |

Initial history: 1999Q2–2018Q4. Development validation: 2019Q1–2023Q3
(19 targets per LGA, 589 per method). Reserved final modelling evaluation:
2023Q4–2025Q3 (eight targets per LGA, 248 per method).

## Validation and final results must remain separate

| Method | Validation MAE | Validation RMSE | Final MAE | Final RMSE |
|---|---:|---:|---:|---:|
| Last observation | 10.9728 | 16.2303 | 13.6089 | 19.4388 |
| Half-adjusted change Ridge | 10.9133 | 15.4055 | 13.1493 | 18.3265 |
| Earlier level Ridge | 13.2135 | 18.6421 | 13.7226 | 18.6964 |
| Seasonal naive | 25.2937 | 38.9464 | 40.6411 | 47.1694 |

Units: nominal AUD/week. Each LGA-quarter has equal weight. MAE is the primary
metric. RMSE is calculated from individual squared errors, not by averaging LGA
RMSEs. The rounded cells in this summary are descriptive; full numerical evidence
is retained in each local experiment directory.

The correction candidate reduced validation MAE by approximately $0.0595/week
(0.54%) and final-period MAE by approximately $0.4595/week (3.3767%). These are
reductions in forecast error, not rent reductions, forecast-accuracy percentages
or guaranteed future improvements.

The final candidate had lower MAE in 21 LGAs and higher MAE in 10. Its fixed
primary comparison is against last observation; secondary methods were not
selected afterward as alternative winners.

## Fixed method and information boundary

Both trained methods use alpha 1, an intercept, the SVD Ridge solver and a fresh
StandardScaler fitted within each earlier-history training fold. Level Ridge
predicts the level from four rent lags and calendar indicators. The correction
learns quarterly change from three lagged changes and calendar indicators:

```
forecast(t) = observed rent(t-1) + 0.5 * predicted change(t)
```

The 0.5 factor is a fixed heuristic, not a probability or fitted optimal weight.
The procedure refits at each origin. An earlier final-period observation can
enter a later training history, but final errors cannot alter the features,
alpha, damping, history window or model choice. Counts, transport and geography
are not predictive inputs. No after-the-fact clipping or removal of targets is
used.

## Audit trail

- Protocol lock: `d0858bdf46fa6b15c34731f0e41873fb5a2ccfe9`.
- Original notebook 13 execution: `2919a4efa3cb0322b6d307f3b5be2d8df5258655`.
- The executed notebook and narrative report were subsequently recorded in
  research-branch commit `dce9b7b8d929e8cb0601c1104dc3adb314ee357b`.
  CSV evidence remains local under the Git-ignored `data/interim/` directory.
  Recording the notebook does not change its original execution identifier.
- 992 final prediction rows, 496 trained fits and 13 saved CSV evidence tables.
- Workbook-cell lineage, chronological training/scaler checks, independent
  mathematical predictions, metric reconciliation and output hashes retained.
- The new reusable implementation reproduces those tables. Running that check
  does not add another independent final test or increase the evaluation sample.

## Interpretation and limitations

The candidate was designed after inspecting validation diagnostics. Its validation
advantage is development evidence. The later period was reserved from modelling
scoring, but its observations appeared in earlier descriptive charts: it was not
a pristine blind test.

Only one workbook vintage is available; historical publication lags and revisions
are not reconstructed. This is a reporting-period retrospective evaluation, not
a real-time backtest. Published medians represent changing collections of lettings,
not fixed homes or inflation-adjusted values. Series labels do not independently
harmonise every historical boundary change.

Eight final quarters are limited evidence. The errors share histories and time
periods; no independence assumption, significance test, confidence interval or
prediction interval has been established. No practical-importance threshold or
automatic deployment rule was set. The result is modest and mixed across LGAs.

The final period has now been scored. Do not tune on it and present another run as
a fresh test. Future improvements require disclosed development and additional
independent evidence. Any deployment proposal needs a separate review, a current
source snapshot and an honest description of forecast limitations.

## Current decision

Preserve the complete research record, including the unsuccessful level-Ridge
result, and consolidate the implementation with automated tests. Keep the online
explorer unchanged. Do not claim a production forecasting service or a current-rent
forecast from this historical dataset.

## Evidence

- [Baseline findings](rental_forecast_baselines.md)
- [Level-Ridge findings](rental_ridge_validation.md)
- [Error diagnostics](rental_ridge_diagnostics.md)
- [Correction candidate](rental_correction_validation.md)
- [Fixed final protocol](rental_final_evaluation_protocol.md)
- [Final results](rental_final_evaluation.md)
- [Refactor and equivalence checks](forecasting_refactor.md)
