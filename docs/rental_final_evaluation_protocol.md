# HomeReach Melbourne — Locked final-period evaluation plan

## Status: specification only; no final scores

This is the plan to record **before** producing forecast errors for **2023Q4–2025Q3**.
It adds no trained model, prediction file, notebook, application feature or data update.
The read-only checker does not open the rental CSV, workbook, prediction exports,
model metrics, or deployed dataset. It reads configuration and local Git records only.

Development evidence is recorded at commit
`f6e16e1359408f37f1e6c7272d13c7594b2c3417` on `feat/rental-forecast-baselines`.
The correction candidate was designed after validation diagnostics and improved
validation MAE by only approximately AUD 0.0595 per week. That is development
evidence, not independent proof of practical value or future performance.

**Do not change the earlier protocols' validation cutoffs.** Their prohibition on
final-period scoring remains in force for notebooks 09–12. A separate, later final-
evaluation notebook will implement this plan without rewriting earlier evidence.

## Question and primary comparison

Does the **already specified damped-change Ridge candidate** have lower mean
absolute error than **last observation** over the reserved later period?

The primary candidate is `damped_change_ridge_alpha1_weight05`:

`forecast(t) = rent(t−1) + 0.5 × predicted_change(t)`

Its unchanged settings are three lagged quarterly changes, target Q2/Q3/Q4
indicators, fold-specific `StandardScaler`, and `Ridge(alpha=1.0,
fit_intercept=True, solver="svd")`. Fit a separate model for each LGA/property.
The learning target is `rent(t) − rent(t−1)`. There is no new tuning, clipping,
rounding, threshold, per-area selection or oracle based on the target's eventual direction.

The earlier direct-level Ridge and seasonal-naive methods remain **secondary
references**, not alternative winners to be promoted after inspecting these results.
All four methods are reported on the same targets. The two trained methods keep
the full settings specified in their original configuration files.

## Fixed scope and forecast counts

| Decision | Fixed plan |
|---|---|
| Source | Audited September 2025 rental-workbook vintage |
| Target | Published nominal median weekly rent, AUD/week |
| Dwelling category | 2 bedroom flats |
| Areas | The same 31 rental-source metropolitan LGAs |
| Final target quarters | 2023Q4 through 2025Q3 inclusive: 8 quarters |
| Forecast horizon | One quarter ahead |
| Targets per method | 31 × 8 = 248 |
| Four-method comparison | 992 prediction rows |
| Primary contrast | Correction candidate minus last-observation absolute error |
| Primary metric | MAE, equal weight for every LGA-quarter |
| Supporting metrics | RMSE and mean signed error (forecast minus actual) |
| Reporting | Overall, per LGA and per target quarter |
| Deployment | None; the explorer remains descriptive |

No new data source, transport feature, geographic feature, published-count
predictor, population weight or selected subset of easier targets is introduced.

## Rolling one-quarter evaluation — not one eight-quarter forecast

The **procedure is fixed; fitted coefficients are not frozen**.

For target 2023Q4, use observations through 2023Q3. For target 2024Q1, use
observations through 2023Q4. Continue in this order until predicting 2025Q3
from information through 2025Q2. An earlier final-period observation can enter
later training history only after its quarter has passed. Its error must never
alter the chosen model, feature definitions, penalty, damping, evaluation window,
or scoring rules.

At each area/origin, refit the scaler and trained model on **earlier eligible
supervised targets only**. The first training target remains 2000Q2, after the
four-quarter warm-up. That gives 94 training examples per area at the first
final forecast and 101 at the last. Each trained method needs 248 fits; the
candidate and direct-level reference together need 496. Baselines require no fit.
Construct each prediction before attaching its actual outcome for scoring.

This is period-based retrospective evaluation. One workbook does not reconstruct
historical publication delays or revisions; do not describe it as a real-time
backtest. The final outcomes have appeared in earlier EDA and the explorer, so
this period is **reserved from modelling evaluation, not a pristine blind test**.

## Interpretation is fixed before the scores

For each target, define:

`paired difference = |candidate − actual| − |last observation − actual|`.

A negative mean favours the candidate on this period; a positive mean favours
last observation. Report the dollar difference and relative MAE reduction.
When the baseline MAE is zero, the percentage is undefined, not zero or infinity.
A `1e-9` AUD/week tie tolerance is only for numerical equality, not a practically
meaningful improvement threshold. Describe such results as numerically tied and
retain last observation as the simpler reference, not a deployment decision.

Report the secondary metrics even when they disagree with MAE. Calculate pooled
RMSE from all individual squared errors, not by averaging LGA RMSEs. Do not blend
validation and final-period errors into a new headline result. Display the
per-area and per-quarter pattern, without claiming 248 statistically independent
observations. No p-values, iid confidence intervals, predictive intervals or
statistical-significance claims are specified. A lower score alone does not
trigger app integration, and no minimum practically useful gain has been established.

Every target stays in the evaluation. Preserve finite negative predictions and
flag them rather than introducing after-the-fact clipping. Missing/duplicate
coverage or a non-finite prediction stops the run for investigation.

## Verification required in the later scoring notebook

The final implementation must check source fingerprints, identical target grids,
chronological lag lineage, training/scaler scope and previous validation evidence.
It must include fictional tests showing that a forecast does not change when
its own actual outcome or a later outcome changes. Independently check the fitted
predictions and baseline source observations, reconcile metrics, and reload exports.
Record Python/library versions, the frozen protocol digest, its pre-scoring
commit and the scoring-code commit. Keep the original 09–12 outputs unchanged.

The planned output directory is `data/interim/rental_final_evaluation`.
**It is not created by this update.**

## Read-only checker

The supplied checker requires only Python's standard library and Git. It checks
four earlier protocol files against canonical JSON fingerprints, allowing LF/CRLF,
indentation and object-key order differences but not changed values or list order.
It also checks the research branch, the target-count arithmetic and that earlier
protocols are already committed. The expected canonical digest of this final plan is:

`f0168e345aafba1a64b883bef1fe351185d7cf57575ce870f252301b484d1495`

Run from the project root, with the existing environment active:

```text
python scripts/verify_rental_final_protocol.py
```

Before the three new files are committed, a successful preflight prints
`Protocol files recorded in HEAD: False`. That is expected. It is not permission
to score the final period. After reviewing and committing all three files, run:

```text
python scripts/verify_rental_final_protocol.py --require-committed
```

This mode rejects missing, modified or differently staged protocol files, and
prints the protocol commit and current HEAD. It does not contact GitHub, push
anything, read rental observations, fit models or create project files. It cannot
prove that outcomes were never viewed or that future scoring code is correct.
Fingerprints are an integrity check, not a malicious-edit security boundary.

## Record the plan before evaluation

Review the plan, then stage just:

```text
git add config/rental_final_evaluation_protocol.json docs/rental_final_evaluation_protocol.md scripts/verify_rental_final_protocol.py
git --no-pager diff --cached --stat
git status
```

Stay on `feat/rental-forecast-baselines`. When the three-file selection is correct:

```text
git commit -m "research: freeze final rental forecast evaluation protocol"
python scripts/verify_rental_final_protocol.py --require-committed
git push -u origin feat/rental-forecast-baselines
git status
```

Stop on a failed check instead of editing the expected fingerprint. Do not use
force push, merge into main, open the final period for exploratory error analysis,
retune after scoring, or publish forecasts. The next checkpoint is the committed
protocol verification and branch status, not a new accuracy table.

## Handling an error discovered after scoring

Preserve the original attempt, identify and document the implementation bug,
state what outcomes were exposed, and rerun the unchanged intended procedure.
Do not erase an unfavourable result or represent a corrected run as a fresh test.
A changed modelling design after seeing final scores needs new independent evidence.

## Method references

- Hyndman and Athanasopoulos, *Forecasting: Principles and Practice*: rolling-origin evaluation and forecast errors. https://otexts.com/fpp3/tscv.html
- scikit-learn: separating model development and final evaluation. https://scikit-learn.org/stable/modules/cross_validation.html
- scikit-learn: fitting preprocessing only on training data. https://scikit-learn.org/stable/common_pitfalls.html

These references motivate the method. The exact dates, candidate, comparison and
stopping rule above are HomeReach's own recorded design decisions.
