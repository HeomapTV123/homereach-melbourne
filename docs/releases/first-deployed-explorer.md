# HomeReach Melbourne — first deployed explorer

**Milestone:** a hosted descriptive rental-and-transport explorer, backed by a
portable, verified snapshot. This file records the first deployed implementation;
it does not claim the full research roadmap is complete.

[Open the hosted app](https://homereach-melbourne-kbytxx6wtdxw3sxas656gh.streamlit.app/) · [Project overview](../../README.md)

## Release identity

| Identifier | Recorded value |
|---|---|
| Deployment code commit | [`35b84e700f373e5d9c8538bbf696c1dbf7d07d65`](https://github.com/HeomapTV123/homereach-melbourne/commit/35b84e700f373e5d9c8538bbf696c1dbf7d07d65) |
| Commit message | `feat: package portable real-data explorer release` |
| Data-release prefix | `fe2035fbc37e64a4` (sidebar shows `fe2035fbc37e`) |
| Full data-release identifier | See [`deploy/data/release_manifest.json`](../../deploy/data/release_manifest.json) |
| Data package creation time | `2026-10-30T18:12:19.520215+00:00` (UTC) |
| Hosted entry point | `deploy/streamlit_app.py` |
| Requested hosting Python | 3.12 |
| Published package | Eight CSVs, one GeoJSON, source attribution and manifest: **11 files** |
| Payload size reported by local packager | Approximately 4.56 MiB |

The Git commit identifies source code and repository contents. The data-release
ID identifies the packaged data snapshot; it is not a semantic-version tag and
is not a publisher signature. This record does not create a GitHub Release or
Git tag. Later documentation commits need not change the data-release ID.

## What shipped

The four-page Streamlit app provides a filterable LGA comparison, area-level rental
history and scheduled-service breakdowns, a rental map with source-cell hover
references, and a methodology/attribution page with a downloadable release
manifest. It does not load the original synthetic demo as a fallback.

The scope is 31 rental-source metropolitan LGAs, two-bedroom flats, 2025Q3 rent
comparisons, 1999Q2–2025Q3 rental history, ABS 2025 boundaries and selected GTFS
feeds 2/3/4 for **13 October 2026**. Morning means **07:00 inclusive–09:00 exclusive**
in Australia/Melbourne service-day time.

## Verification evidence

The maintainer's local run reported **352 passed**. Packaging matched all nine
data payload files to the validated local explorer bundle and wrote 11 release
files. Standalone verification reported 31 comparison LGAs, 3,286 rental-history
rows, no upstream reports read and no raw datasets read.

[GitHub Actions run #16](https://github.com/HeomapTV123/homereach-melbourne/actions/runs/41113511058)
for the deployment commit completed successfully. Its reported result was
**352 passed, 823 warnings**. These are pandas deprecation warnings, not failed
tests: CSV `float_precision` usage and filling a numeric intermediate with text
need compatibility review. No warning-suppression or data changes are part of
this documentation update.

The release has 158,932 counted AM departure events and 5,768 distinct AM trips
across the selected study area. These are different measures. The sum of
LGA-specific distinct AM trip counts is 12,546, which is not a network total.
See the [service method](../gtfs_service_indicators.md) and
[combined analysis](../transport_rent_eda.md).

## Hosted screenshots: what they demonstrate

| Browser evidence | Observation | Screenshot |
|---|---|---|
| Default comparison | 31/31 LGAs; displayed medians span $400–$730/week | [Comparison](../assets/explorer-compare.png) |
| Empty-result handling | A $390 ceiling shows a clear no-matching-LGAs message, without a visible traceback | [Empty filter](../assets/explorer-empty-filter.png) |
| Area details | Melbourne displays $730, 1,633 distinct AM trips and 579 served stop records; rental-history chart is visible | [Area](../assets/explorer-area.png) |
| Rental map | Polygons and legend render; Yarra Ranges hover shows $530, count 48 and `2br Flat!HF78` | [Map](../assets/explorer-map.png) |
| Methodology | Different source periods and event-counting rules are displayed; further supplied screenshots show attribution and the release record | [Methodology](../assets/explorer-methodology.png) |

The screenshots were supplied by the maintainer from the hosted application.
The stored PNGs are cropped to omit browser chrome and surrounding controls;
no displayed data values, results or charts were altered. The comparison image
comes from the earlier successful default-state capture; the other images come
from the later page checks.

**Evidence limits:** these captures do not independently establish anonymous or
signed-out access, downloaded CSV contents, every control interaction, mobile
layout or performance under concurrent users. Those checks remain unconfirmed
by the supplied screenshots. A screenshot is not a substitute for those tests.

## Running this same packaged release

In a checkout with serving dependencies installed:

```bash
python scripts/verify_explorer_release.py
python -m streamlit run deploy/streamlit_app.py --server.port 8503
```

The app reads the frozen release, not the original GTFS, Excel or shapefile
archives. It does not rerun pipelines on each interaction or refresh sources
when their publishers update them. Keep the packaged files and
[`deploy/.gitattributes`](../../deploy/.gitattributes) together.

The full [deployment guide](../explorer_deployment.md) distinguishes this entry
point from the local upstream-validated explorer and the synthetic demo.

## Known limits and follow-on work

This is not a real-time listing service, income-based affordability model,
recommendation engine, rent forecaster or routing application. Counts do not
measure actual vehicles, riders, reliability, capacity, regular headways or a
useful journey to a selected destination. A single schedule date does not
establish stable service; LGA totals do not measure residential walking access.
The different rental and transport dates remain explicit.

Next work should keep this working release as a reference while evaluating
compatibility fixes, UX feedback and separately validated analytical extensions.
In particular, a rental-forecast experiment needs chronological evaluation and
a seasonal-naive baseline; the 2026 schedule must not be used as evidence of
historical transport conditions in past rental evaluation periods.

[Source attribution and licence evidence](../../deploy/DATA_SOURCES.md) applies
to the source datasets and derived outputs as described there. This record does
not grant a new licence to HomeReach's source code or claim official endorsement.
