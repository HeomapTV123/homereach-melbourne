# Definition of Done

A feature is complete only when all relevant conditions below are met.

## Data

- The source and reporting period are recorded.
- Raw data remains unchanged.
- Column names and units are documented.
- Missing and suppressed values are handled explicitly.
- Primary-key uniqueness is tested.
- Join coverage and unmatched records are reported.
- Geographic and time vintages are displayed to the user.

## Analysis

- A baseline exists before an advanced model.
- Time-dependent data is split chronologically.
- Metrics are reported on unseen data.
- Results are compared across areas and property types where possible.
- Uncertainty and limitations are visible.
- Protected characteristics are not used to rank renters or neighbourhoods.

## Application

- Inputs have sensible defaults and validation.
- Every recommendation can be explained through component scores.
- The app never presents a preference score as objective truth.
- Synthetic data is labelled.
- Empty results and missing files fail gracefully.
- Data dates appear on the page.

## Engineering

- Reusable logic is in `src/`, not only notebooks.
- Tests pass with `pytest`.
- Configuration is not hard-coded throughout the project.
- Processed tables are reproducible from documented commands.
- No keys, passwords or confidential data are committed.

## Portfolio

- README covers the problem, users, architecture, data, methods, results,
  limitations and screenshots.
- A two-minute demo can be completed without debugging.
- The repository contains a model card and data dictionary.
- Resume bullets use measured outcomes rather than vague claims.
