# HomeReach Melbourne — Transport and rental snapshot comparison

Generated (UTC): 2026-10-20T16:45:39.827030+00:00

## Scope

Rental period: **2025Q3**; 2 bedroom flats. Transport date: **2026-10-13**, Australia/Melbourne, 07:00 inclusive–09:00 exclusive.
The same 31 reviewed source-group metropolitan LGAs use the ABS 2025 identifiers. Feed scope remains 2,3,4; labelled replacements stay separate.
This joins differently dated snapshots. No combined score, accessibility estimate, regression, prediction or recommendation is made.

## Verified arithmetic

- AM eligible departure events: 158,932.
- Distinct AM trips across the study area: 5,768.
- Sum of LGA-specific distinct AM trip counts: 12,546; this is NOT the distinct study-area total.
- Assigned stop/platform records: 21,426; with counted AM events: 20,448; with no counted AM event: 978.
- The 248-row service grid reconciles with the stop and trip-membership outputs. All 31 rental rows matched; all 14 original rental fields were preserved.
- Six analytical self-check groups passed; these do not add to the project's pytest suite.

## Descriptive observations from the supplied sources

- An LGA with the largest AM event count is Melbourne: 14,096 events, 1,633 distinct local contributing trips.
- An LGA with the largest distinct AM trip count is Melbourne: 1,633 trips.
- Lowest published LGA median rent in this subset: $400/week (Brimbank). Highest: $730/week (Melbourne).
These are order statistics, not area recommendations. Ties in the comparison tables remain present.

## How to read the four charts

1. **Morning events by category:** a raw-volume comparison. More stop visits do not necessarily mean more useful routes or better residential access.
2. **Events versus distinct trips:** the metrics differ because a trip calls at multiple stops and may visit multiple LGAs. No network trip total is obtained by adding LGA counts.
3. **Two stop-record denominators:** compare events divided by all assigned records versus only served records. These means describe source records; they are not headways, passenger waits, physical-station counts or population-weighted access.
4. **Rent versus morning trips:** horizontal rent values are 2025Q3, vertical service values are 2026-10-13. The scatter is not contemporaneous causal evidence or a forecast.

## Cautions

LGA extent, route arrangements and stop placement affect raw counts. Repeated/co-located records across feeds remain separate. Counts do not measure riders, vehicles, capacity, actual punctuality or commute time.
A stop outside the polygons may serve residents inside; no walkshed or destination analysis has been performed. Near-boundary counts remain diagnostic, not error probabilities.
Assigned locations with no counted AM event may be inactive, terminal-only, no-pickup, or affected by the selected service date and window. Zero does not prove absence of useful transport.
Rent is an area-level nominal median based on the publisher's methodology, not a current listing, household-income affordability score, or price of a fixed property. Do not average LGA medians to manufacture a metropolitan median.
Do not backfill the 2026 transport snapshot into historical rental model validation. A single weekday snapshot does not prove stable or disruption-free service.

## Outputs

Six CSV analysis tables and four self-contained HTML charts under data/interim/transport_rent_eda/. The manifest records definitions, schema and fingerprints.
The input data, original notebooks, registry and Streamlit demo are not overwritten. Rerunning this final cell replaces this generated report; keep personal reflections separately.

## Field definitions

- am_departure_events: sum of eligible stop visits within one LGA in the two-hour morning window.
- am_unique_trip_records / am_unique_route_records / am_served_stop_records: distinct feed-prefixed identities in that LGA/window.
- am_events_per_counted_trip: events divided by the distinct contributing trip count; a stop-call ratio, not a frequency.
- mean_am_events_per_assigned_stop_record: events divided by all assigned source stop/platform records, including zero-event records.
- mean_am_events_per_served_stop_record: events divided by assigned records with at least one eligible AM event; undefined if none.
- assigned_record_share_with_counted_am_event_pct: record-level fraction only, not the fraction of residents with transit access.
- am_share_of_service_day_events_pct: AM event subset divided by full-service-day events; extended times are retained in the day total.
- quarter / quarter_end / published_count / median_weekly_rent: the original rental fields. transport_service_date and transport_timezone are separate.

## Primary references

- https://www.dffh.vic.gov.au/publications/rental-report
- https://gtfs.org/documentation/schedule/reference/
- https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.merge.html
- https://plotly.com/python/interactive-html-export/
