# Project Charter

## Working title

HomeReach Melbourne

## Problem

People comparing Melbourne rental locations must combine rent, transport,
commute and environmental information from separate sources. This project
creates a transparent prototype that brings those trade-offs together.

## Primary user

A renter, student or early-career worker comparing areas under a weekly
budget and a maximum commute preference.

## Secondary user

An analyst or planner exploring where rental pressure, transport access and
historical environmental disadvantage overlap.

## Decision supported

Which areas are the best fit under the user's selected constraints and
weights?

## Core output

A ranked shortlist, map, historical rent trend, component-score
explanation and clearly stated limitations.

## Minimum viable scope

- LGA-level rental analysis
- one selected property type: two-bedroom flats, with the exact source
  category label to be confirmed during the rental-data audit
- scheduled metropolitan transport indicators
- transparent scoring
- a deployed Streamlit application
- reproducible data-quality checks

## Non-goals for the first release

- scraping live property listings
- predicting individual property prices
- labelling areas as objectively good, bad, safe or unsafe
- using personal or protected characteristics for ranking
- claiming scheduled travel is actual on-time performance
- claiming forecasts are guaranteed

## Success measures

- zero duplicate rows at the declared analytical key
- all unmatched geographic joins reviewed and reported
- every displayed score can be traced to source features and weights
- model evaluation uses chronological holdout data
- final model is compared with a seasonal-naive baseline
- automated tests pass locally and in continuous integration

## Initial implementation boundaries

The first data pipeline will use metropolitan Melbourne Local Government
Areas and the published rental category corresponding to two-bedroom flats.
The source's exact category label will be confirmed during the Week 2 audit.

The first recommendation version will use rental affordability and
scheduled public-transport indicators.

Destination-specific commute routing, rental forecasting, environmental
layers and finer rental-area geography will be added only after the core
rental-and-transport pipeline is working.

The starter application's synthetic commute, environment and forecast
values are demonstration inputs, not completed real-data features.
