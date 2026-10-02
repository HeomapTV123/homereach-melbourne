# Rent Forecast Model Card

## Model purpose

Predict area-level median weekly rent for a future quarter. This is a
planning and portfolio demonstration, not financial advice or a guarantee.

## Unit of prediction

One LGA or reviewed rental area × one property type × one target quarter.

## Target

`median_weekly_rent`

## Candidate models

1. Seasonal-naive baseline
2. Ridge regression
3. Tree-based regression model

## Data split

Chronological only. Record the exact training, validation and test quarters.

## Features

Record all lag, rolling, seasonal, geographic and transport features.
Rolling features must use only information available before the target
quarter.

## Metrics

- Mean Absolute Error
- Weighted Absolute Percentage Error
- Error by property type
- Error by geography
- Comparison with baseline

## Limitations

- Published medians describe an area, not an individual property.
- Rental bond data is a proxy for new lettings and excludes specified
  accommodation types.
- Future policy, supply, economic conditions and shocks may differ from
  training history.
- Transport associations do not establish a causal effect on rent.
- Prediction intervals represent model uncertainty, not every possible
  outcome.

## Release decision

Use the advanced model only when it performs meaningfully better than the
baseline on untouched test quarters and passes leakage checks.
