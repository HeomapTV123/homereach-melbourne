# HomeReach Melbourne — public snapshot attribution

Independent student project. No publisher endorsement is implied. This page
attributes the source data, not government logos or website design. No logo,
photograph, website layout or claim of official affiliation is included.
This document does not assign a licence to the user's application code.

## Rental statistics

**Source:** Homes Victoria / Department of Families, Fairness and Housing,
State of Victoria. *Quarterly median rents by Local Government Area —
September quarter 2025.* The snapshot contains 1999Q2–2025Q3 observations;
the comparison shows 2025Q3 two-bedroom flats for 31 source-group LGAs.

- Dataset: https://www.dffh.vic.gov.au/publications/rental-report
- Dataset-specific licence listing: https://discover.data.vic.gov.au/dataset/rental-report-quarterly-quarterly-median-rents-by-lga
- Licence listed for that dataset: CC BY 4.0, https://creativecommons.org/licenses/by/4.0/
- HomeReach changes: selected one dwelling category and reviewed LGAs,
  reshaped tables and attached LGA codes; source rent/count values and
  original workbook cell references retained.

The data catalogue's licence listing concerns the downloadable dataset.
Do not assume it licenses unrelated DFFH website text, photographs, branding
or layout. In particular, the general DFFH website copyright page has separate
terms: https://www.dffh.vic.gov.au/copyright . No website design is reproduced.

## Transport indicators

**Source:** State of Victoria, Department of Transport and Planning,
Transport Victoria, *GTFS Schedule*. Derived for 13 October 2026,
Australia/Melbourne service-day time, from the previously audited archive.

- Dataset and licence listing: https://opendata.transport.vic.gov.au/dataset/gtfs-schedule
- Licence: CC BY 4.0, https://creativecommons.org/licenses/by/4.0/
- HomeReach changes: selected feeds 2/3/4, applied calendars and exceptions,
  spatial assignment, regular-pickup and complete-trip terminal rules, then
  aggregated by LGA/category/window. Morning: 07:00 inclusive–09:00 exclusive.
- This release includes aggregates, not the raw GTFS archive or stop/trip-level
  tables. It is scheduled supply, not observed vehicle performance.

## Boundaries

**Source:** Commonwealth of Australia, Australian Bureau of Statistics,
*ASGS Edition 3 — Local Government Areas 2025, GDA2020*.

- Dataset and licence listing: https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs/edition-3-july-2021-june-2026/access-and-downloads/digital-boundary-files
- Licence: CC BY 4.0, https://creativecommons.org/licenses/by/4.0/
- HomeReach changes: selected 31 reviewed LGAs and transformed their coordinates
  to WGS84 for web display. No simplification or geometry repair.
- ABS boundaries are statistical approximations, not legal boundary definitions.

## Publication notes

Licence metadata was reviewed on 26 October 2026. Retain publisher names,
source links, licence links and the descriptions of processing when sharing
these derived outputs. Updated or additional datasets need their own review.
The release app displays this attribution on Data and methodology and includes
machine-readable attribution in `deploy/data/source_attribution.json`.

Published medians are not live listings. The transport date is more than a year
later than the rental comparison period. No causal claim, score or forecast is
made. Source website updates do not automatically refresh this frozen release.
