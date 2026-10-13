# HomeReach Melbourne — Date-specific scheduled service indicators

Generated (UTC): 2026-10-12T17:52:36.037017+00:00

## Scope

- Service date: **2026-10-13**, Australia/Melbourne GTFS service-day time.
- Rental reporting snapshot remains 2025Q3; do not use this schedule as historical rental-model evidence.
- Operational feeds: 2, 3 and 4; the other five archives are outside the detailed scope.
- Study area: the same 31 reviewed source-group metropolitan LGAs.
- GTFS source SHA-256: `c88af3abcaf0872e45196dcc1d5af9bc20a82c54a00a9dfef46c809ec2e34814`.
- Prior stop assignments and crosswalk were verified against their local manifests.

## Counting rule

One event is one active `(feed_id, trip_id, numeric stop_sequence)` record. Count it only when pickup is regular
(0, including blank), the complete trip has a later stop sequence, and the stop lies inside one selected LGA.
Final records are excluded even if the vehicle might continue as a linked trip. No-pickup (1) and arrangement-required
(2/3) records are kept as separate exclusion counts. This is a scheduled-event proxy; downstream alighting, transfers,
capacity, walking catchments and accessibility are not solved.

The complete-trip terminal is calculated BEFORE filtering stops by LGA or departure time.
The full selected service day retains 24:00+ times; the AM window is 07:00 inclusive to 09:00 exclusive.
No modulo-24 conversion is used. Adjacent service-date trips are not merged into a calendar-day inventory.

## Counts within the selected LGAs

| Category | Window | Counted departure events | Distinct trip records | Served stop records | Distinct route records |
|---|---|---:|---:|---:|---:|
| labelled_replacement_bus | am_peak_0700_0900 | 0 | 0 | 0 | 0 |
| myki_bus | am_peak_0700_0900 | 122,943 | 4,312 | 18,358 | 422 |
| train_not_labelled_replacement | am_peak_0700_0900 | 7,347 | 569 | 484 | 16 |
| tram | am_peak_0700_0900 | 28,642 | 887 | 1,606 | 23 |
| labelled_replacement_bus | service_day | 480 | 52 | 27 | 3 |
| myki_bus | service_day | 901,004 | 24,178 | 18,825 | 477 |
| train_not_labelled_replacement | service_day | 46,081 | 2,776 | 496 | 16 |
| tram | service_day | 227,716 | 5,044 | 1,607 | 24 |

Counts above are distinct across the study area for each category/window. Do not sum LGA trip counts
to obtain a network total: the same trip can provide eligible visits in several LGAs.

## Verification

- Source stop-time rows scanned: 11,847,183.
- Active trip records: 35,580; active stop-time rows: 1,311,746.
- Complete LGA/category/window grid: 248 rows (31 × 4 × 2).
- Duplicate active event keys and missing active-event trip/stop references: 0.
- Complete-trip terminal counts, selection partitions, stop totals and trip memberships reconciled.
- Three calendar self-check groups and ten service-policy self-check groups passed.
- Nine CSV exports reloaded and matched; upstream input files remained unchanged.
- No raw timetable rows were overwritten; the registry, previous notebooks and app were not edited.

## Reading the output tables

- `lga_service_indicators.csv`: the main 248-row analytical table, including zero-count combinations.
- `stop_service_indicators.csv`: counted stop/category/window combinations only; upstream retains all other stops.
- `trip_lga_memberships.csv`: distinct trip/area/window links for independent count verification.
- `active_trip_lookup.csv` and `trip_stop_scope.csv`: date selection and complete-trip scope.
- `feed_service_summary.csv`: counts across the selected LGAs, already deduplicated across areas.
- `event_filter_audit.csv`: exhaustive EXCLUSIVE outcome counts (terminal checked before pickup before location).
- `scan_summary.csv`: source/read/active totals per feed.
- `event_trace_examples.csv`: a labelled sample for checking source line/trip/sequence and exclusion reasons.
- `service_indicators_manifest.json`: source fingerprints, policy, schemas and output fingerprints.

## Interpretation cautions

These are scheduled stop-record visits, not riders, actual departures, separate vehicles or regular route headways.
A repeated visit on the same trip contributes another event but not another unique trip in the same LGA/window.
A route ID is not necessarily a unique passenger-facing route brand; identical cross-feed IDs remain separate.
The replacement category uses the explicit source label only; non-labelled feed-2 trips remain labelled cautiously.
The Myki feed includes regional services; outside and non-eligible records are excluded from area totals, not erased.
A stored stop outside the polygons can still serve nearby residents. The 10 m boundary flag is diagnostic only.
Zeros mean no counted events under this scope and rule, not proof of no useful transport for residents.
LGA totals are affected by area size and route/station arrangement. No normalisation, score, ranking or forecast is made.

## References

- https://gtfs.org/documentation/schedule/reference/
- https://opendata.transport.vic.gov.au/dataset/gtfs-schedule
- https://pandas.pydata.org/docs/reference/api/pandas.read_csv.html
