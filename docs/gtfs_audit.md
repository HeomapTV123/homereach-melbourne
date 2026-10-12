# HomeReach Melbourne — GTFS snapshot audit

Generated (UTC): 2026-10-11T15:32:00.726572+00:00

## Source and scope

- Source file: `gtfs.zip`; 229,799,804 bytes.
- SHA-256: `c88af3abcaf0872e45196dcc1d5af9bc20a82c54a00a9dfef46c809ec2e34814`.
- Eight numbered inner GTFS archives. Detailed checks cover feeds 2, 3 and 4 only.
- Agency timezone: Australia/Melbourne. No spatial filtering or LGA service score has been produced.
- Original archive and existing rental/geography input files remained unchanged.
- No download date is inferred from filesystem/ZIP timestamps. Publisher page metadata was observed as 9 October 2026.

## Selected-feed inventory

| Feed | Location rows | Route rows | Trip rows | Stop-time rows checked |
|---|---:|---:|---:|---:|
| 2 — Metropolitan train operational feed | 2,859 | 36 | 40,556 | 688,380 |
| 3 — Metropolitan tram | 1,623 | 24 | 55,599 | 2,568,892 |
| 4 — Myki bus: metropolitan + regional town | 22,633 | 762 | 215,328 | 8,589,911 |

Counts describe records, not daily vehicles, unique passenger route brands or stations.

## Proposed date and calendar effects

- Proposed date: **Tuesday, 13 October 2026**, in Australia/Melbourne service-day time.
- Selected calendars span 8 October–31 December 2026 (85 days). This longer raw extent is not a coverage guarantee.
- Transport Victoria describes a rolling 30-day publication window and warns some route information may be incomplete.
- All three feeds have active service IDs on the proposed date; this is not proof it is disruption-free.

| Feed | Trips before exceptions | Trips after exceptions | Active route IDs | Labelled replacement trips |
|---|---:|---:|---:|---:|
| 2 | 2,828 | 2,828 | 19 | 52 |
| 3 | 10,088 | 5,044 | 24 | 0 |
| 4 | 81,004 | 27,708 | 653 | 0 |

These are full operational-feed counts. Regional bus records and replacement services have not been removed.

## Validation result

- 11,847,183 stop-time rows were scanned in chunks; not sampled.
- Duplicate (trip_id, stop_sequence) keys, including across chunks: 0.
- Undefined stop-time trip or stop references: 0.
- Blank/invalid arrival and departure times in selected snapshot: 0.
- Invalid sequences, pickup/drop-off codes and within-row arrival-after-departure values: 0.
- Every selected trip has stop times. Every referenced location is a stop/platform.
- 250,932 departure-time rows use 24:00:00 or later; these are retained as valid service-day times.
- Five helper self-check groups passed; they are notebook checks, not additions to the existing pytest test count.

## Decisions and cautions

- **Operational scope:** Detailed audit covers feeds 2, 3 and 4 only. Report omitted regional/interstate/airport feeds; do not call this all transport.
- **Study area:** Myki bus includes regional-town services; no LGA filtering performed. Spatially join stop/platform points to the validated 31-LGA geometry.
- **Replacement services:** Feed 2 has 18 labelled replacement routes; 52 related active trips on 2026-10-13. Keep replacement-route trips distinct; feed 2 and route_type 400 do not guarantee a train.
- **Identifier namespaces:** 12 shared rail/tram service IDs; 41 shared tram/bus stop IDs. Use (feed_id, raw_id); do not collapse cross-feed records automatically.
- **Location hierarchy:** Train locations include platforms, stations, entrances and generic nodes. Do not count all stops.txt rows as stations or boarding stops.
- **Wheelchair information:** All selected tram and bus wheelchair_boarding values are 0; train values vary. Preserve unknowns and parent-inheritance semantics; no accessible-journey score yet.
- **Service dates:** Calendar extent is 85 days, longer than the publisher's stated rolling 30-day window. Use the audited nearby candidate date; do not infer complete timetable coverage from endpoints.
- **Boardable services:** Stop-time rows include terminal visits and some no-pickup records. Filter by active services, pickup policy and onward stop before interpreting boarding frequency.
- **Temporal alignment:** Rent is 2025Q3; proposed transport service date is 2026-10-13. Display both dates; never insert this current feed into historical rental backtests.
- **Validation limits:** Shapes, transfers, pathways, all inter-stop time ordering and real operations not validated. Keep the result labelled a scoped schedule audit, not complete GTFS certification.

## Next step

Review this evidence, then prepare namespaced stop/platform points for the 31-LGA spatial join.
Preserve exact stop IDs, feed IDs, service date, coordinate datum and replacement-route flags.
Do not update scores or the demonstration app from these raw inventory counts.

## Reproduce

Run `notebooks/05_gtfs_audit.ipynb` with the existing homereach kernel and the unchanged source ZIP.
Detailed tables and audit_summary.json are stored under `data/interim/gtfs_audit/`.
This generated report is replaced on rerun; keep personal reflections elsewhere.

## Official references

- https://opendata.transport.vic.gov.au/dataset/gtfs-schedule
- https://gtfs.org/documentation/schedule/reference/
- https://developers.google.com/transit/gtfs/reference/extended-route-types
