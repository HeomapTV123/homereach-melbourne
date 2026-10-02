# Data Dictionary Template

Complete one row for every field that enters a processed table or model.

| Table | Column | Type | Unit | Description | Source | Missing meaning | Allowed values |
|---|---|---|---|---|---|---|---|
| fact_rent_quarter | rental_area_name | string | n/a | Published rental-market area label | DFFH | Missing row | Published labels |
| fact_rent_quarter | quarter | period/string | quarter | Reporting quarter | DFFH | Invalid parse | YYYYQ1–YYYYQ4 |
| fact_rent_quarter | property_type | category | n/a | Dwelling and bedroom category | DFFH | Not applicable | Documented categories |
| fact_rent_quarter | median_weekly_rent | float | AUD/week | Median for new lettings | DFFH | Suppressed/unavailable | Non-negative |
| fact_transport_service | unique_peak_trips | integer | trips | Distinct active trips serving the area in the chosen peak window | GTFS | Not processed | Non-negative |
| feature_area_quarter | overall_score | float | 0–100 | Weighted preference score | Derived | Required component missing | 0–100 |

Add columns for:

- source reporting date
- geographic vintage
- transformation formula
- quality rule
- whether the variable is used in ranking, context only, or modelling only
