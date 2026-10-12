# HomeReach Melbourne — Transport-stop spatial join

Generated (UTC): 2026-10-12T14:25:32.107880+00:00

## Inputs and scope

- GTFS snapshot SHA-256: `c88af3abcaf0872e45196dcc1d5af9bc20a82c54a00a9dfef46c809ec2e34814`.
- Boundary snapshot: ABS LGA 2025; SHA-256 `acc3015a0ac78ade978c41a2e4110269b5219b60d6a56cbb70393ae647f31b15`.
- Study area: the same 31 reviewed rental-source metropolitan LGAs, not a newly substituted metro definition.
- Detailed operational feeds: 2, 3 and 4; other five feeds remain outside this stage.
- All selected-feed location rows: 27,115; selected stop/platform rows: 25,031; hierarchy rows retained separately: 2,084.
- GTFS blank location_type is interpreted as 0. Raw values and all source fields are preserved.
- One record is a (feed_id, stop_id) pair. Cross-feed identical IDs and co-located records are not deduplicated.
- Planned later service date: 2026-10-13. NO service-date, active-trip, pickup-policy or replacement-trip filtering is performed here.

## Spatial policy

- GTFS WGS84 points and ABS GDA2020 polygons are transformed as copies into EPSG:7855 (metres).
- Assign an LGA only for one unique strict-interior polygon; no nearest-LGA, fuzzy-name, snapping or centroid substitution.
- Exact boundaries, overlapping candidates and invalid coordinates remain separate review outcomes.
- Outside the 31 selected polygons is not synonymous with invalid, regional, inactive or inaccessible.
- The 10 m boundary flag is a chosen sensitivity screen only, not an official accuracy threshold or confidence interval.
- Raw coordinate precision, WGS84 epoch/realisation and ABS statistical-boundary uncertainty prevent survey-level certainty.

## Observed outcomes

| Feed | Outcome | Stop/platform records |
|---|---|---:|
| 2 | matched_within | 775 |
| 3 | matched_within | 1,623 |
| 4 | matched_within | 19,028 |
| 4 | outside_selected_lgas | 3,605 |

- Independent point/polygon checks: 25,031.
- Near-boundary diagnostic records: 443; codes were not changed by this flag.
- Spatial self-check groups: 8; these are notebook checks, not new pytest tests.
- CSV values and GeoPackage attributes/point coordinates matched on read-back.
- Original GTFS, native polygons, reviewed crosswalk, rental files, earlier audits and registry were not overwritten.

## Interpretation

Stored location-record counts are not unique physical stops, railway stations, daily services, frequencies, walking accessibility, or transport quality.
Platforms with the same station name may legitimately lie in different LGAs. Do not force them to inherit a parent station's spatial assignment.
Feed 2 includes replacement-bus operations; infer service mode/flags later from reviewed route/trip information rather than just the feed number or a stop name.
Unknown wheelchair codes and parent values remain raw; no accessible-journey claim is made.
A stop outside an LGA can still serve its residents. Point-in-polygon membership is not a residential catchment analysis.
Rent describes 2025Q3; the proposed transport date is in October 2026. Never insert this newer snapshot into historical rental-model evaluation as past transport evidence.

## Outputs

`data/interim/gtfs_spatial/`: eight CSV tables, `stop_lga_matches.gpkg`, and `spatial_join_summary.json`.
The complete assignment CSV preserves all selected records, including unassigned ones. Candidate associations are a separate table.
All 31 × 3 LGA/feed combinations appear in the location inventory; zero means no assigned stored record, not proven absence of usable services.

## Next stage

Join active trips and boardable stop-time events using both feed and stop/trip IDs; apply calendar exceptions, pickup policies, onward-stop rules and replacement-service flags before calculating service indicators.

## References

- https://gtfs.org/documentation/schedule/reference/
- https://geopandas.org/en/stable/docs/reference/api/geopandas.sjoin.html
- https://geopandas.org/en/stable/docs/user_guide/projections.html
- https://opendata.transport.vic.gov.au/dataset/gtfs-schedule
