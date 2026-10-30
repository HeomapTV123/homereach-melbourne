# HomeReach Melbourne

**Explore published rental costs and scheduled public transport across 31 Melbourne LGAs.**

[Open the deployed explorer](https://homereach-melbourne-kbytxx6wtdxw3sxas656gh.streamlit.app/) · [First deployed release](docs/releases/first-deployed-explorer.md) · [Data sources and attribution](deploy/DATA_SOURCES.md)

HomeReach Melbourne is a data-science project that turns official rental statistics,
transport timetables and geographic boundaries into a reproducible, interactive
comparison. It combines source audits, data cleaning, reviewed geographic joins,
service-indicator engineering, automated tests and a hosted Streamlit application.

> **This is a descriptive explorer of differently dated snapshots.** Rent is from
> **2025Q3**; scheduled transport is for **13 October 2026**; LGA boundaries are
> **ABS 2025**. It is not a live property search, a recommendation ranking, a
> commute-time calculator or a forecasting service.

![HomeReach comparison page showing all 31 LGAs, historical rent filters and scheduled morning transport statistics](docs/assets/explorer-compare.png)

## Why this project?

Comparing areas requires more than ordering a list of rents. Published rental
statistics and transport schedules describe different things, use different
identifiers and cover different periods. HomeReach makes those differences
explicit while giving users a way to inspect the data together.

The current question is: **How do published rents and scheduled morning service
supply vary across the selected LGAs?** It does not assume that a cheap area, or
an area with many stop visits, is automatically a suitable place to live.

## Explore the application

| Page | Implemented functionality |
|---|---|
| **Compare LGAs** | Filter by rental-source region, an optional published-median-rent ceiling and a minimum distinct morning-trip count; sort the table, inspect a scatter plot and download the comparison. |
| **Area details** | Select an LGA; inspect quarterly rental history, morning/full-service-day category breakdowns, stop-record denominators and original Excel source-cell references. |
| **Rental map** | Explore 31 LGA polygons coloured by published median weekly rent. Hover displays the area, reporting period, rental count and source cell. Online background tiles are optional. |
| **Data and methodology** | Read the source periods, event-counting rules, limitations, publisher attribution and frozen-release manifest. |

The default comparison is alphabetical, not a best-to-worst ranking. A rent
ceiling filters an area's published median; it does not establish that an
available property meets that budget.

<details>
<summary>View area details, the rental map, methodology and empty-result handling</summary>

### Area details

![Melbourne area details showing a 730 AUD weekly median, 1633 distinct morning trips and rental history](docs/assets/explorer-area.png)

### Rental map

![LGA rental map with Yarra Ranges hover information and the original workbook cell reference](docs/assets/explorer-map.png)

### Methodology

![Methodology page showing the three source periods, verification boundary and scheduled-event definition](docs/assets/explorer-methodology.png)

### Empty filter result

![A published-rent ceiling of 390 AUD produces a clear no-matching-LGAs message instead of an error](docs/assets/explorer-empty-filter.png)

These are cropped screenshots of the deployed application supplied by the project
maintainer. They illustrate the displayed state; they are not a record of every
possible interaction or proof of anonymous access.

</details>

## Snapshot and analytical scope

| Component | Period and coverage | Source / evidence |
|---|---|---|
| Rental history | **1999Q2–2025Q3**, 106 quarters, 31 selected LGAs, **2 bedroom flats**; 3,286 LGA-quarter rows | [DFFH rental report](https://www.dffh.vic.gov.au/publications/rental-report); [rental pipeline](docs/rental_pipeline.md) |
| Rental comparison | **2025Q3**; one published median and count per selected LGA | [Combined analysis](docs/transport_rent_eda.md) |
| Boundaries | **ABS LGA 2025**, GDA2020; transformed to WGS84 for the web map | [Source attribution](deploy/DATA_SOURCES.md); [geography pipeline](docs/geography_pipeline.md) |
| Transport | **2026-10-13**, Australia/Melbourne service-day time; operational feeds **2, 3 and 4** | [Transport Victoria GTFS Schedule](https://opendata.transport.vic.gov.au/dataset/gtfs-schedule); [transport pipeline](docs/transport_pipeline.md) |
| Morning window | **07:00 inclusive to 09:00 exclusive** | [Service-indicator method](docs/gtfs_service_indicators.md) |

The study area is the rental source's **North and West Metro, Eastern Metro and
Southern Metro** groups. An LGA is a local government area, not an individual
suburb. This scope is not silently replaced by a different definition of Greater
Melbourne.

## From sources to the deployed explorer

```text
DFFH rental workbook       ABS boundaries       Transport Victoria GTFS
        |                        |                         |
   Audit and clean         Review identifiers       Audit feeds/calendars
        |                        |                         |
        +------ LGA crosswalk ---+---- Stop-to-LGA spatial join
                         |                    |
                  Rental statistics   Scheduled-service indicators
                         |                    |
                         +--- Verified comparison ---+
                                                     |
                                    Application-ready local bundle
                                                     |
                                    Allowlisted portable data release
                                                     |
                                     Hosted Streamlit explorer
```

**Rental preparation:** Count and Median columns are kept separate; aggregate rows
are excluded; source filenames, worksheet names and Excel cell references are
retained. The analytical key is `(rental_area_name, quarter, property_type)`.

**Geographic matching:** 28 rental names match exactly. Three reviewed aliases
resolve Bayside, Kingston and the source abbreviation `Mornington Penin'a`.
Stop/platform points are assigned only to one unique strict-interior LGA polygon.
Outside and ambiguous cases are retained, not snapped to the nearest area.

**Transport processing:** Feed-specific identifiers remain distinct. Calendar
exceptions override weekly schedules. Labelled replacement buses stay separate.
A counted departure event requires an active trip, regular pickup, a later stop
in the complete trip and an assigned LGA. Terminal detection happens before
geographic or time filtering. GTFS times at or beyond `24:00:00` are retained for
the complete service day, not wrapped modulo 24.

**Release packaging:** Only eight CSV tables, one GeoJSON, source attribution and
a release manifest are published under `deploy/data`. The serving app reads that
frozen subset, not the raw archives or the developer's upstream reports. Packaged
fingerprints detect changes relative to the manifest; they are not publisher
signatures or independent certification.

## Verification at the first deployed release

The deployed code snapshot is [`35b84e7`](https://github.com/HeomapTV123/homereach-melbourne/commit/35b84e700f373e5d9c8538bbf696c1dbf7d07d65).
Its data-release identifier begins **`fe2035fbc37e64a4`**; the full identifier is in
[the release manifest](deploy/data/release_manifest.json).

| Check | Recorded result |
|---|---|
| Automated test suite | **352 passed** locally and in [GitHub Actions run #16](https://github.com/HeomapTV123/homereach-melbourne/actions/runs/41113511058) |
| Rental-to-boundary join | **31/31 matched**, with no duplicate LGA codes |
| Selected stop/platform records | **25,031**: 21,426 assigned, 3,605 outside the selected polygons retained |
| Stop-time records scanned in the scoped GTFS audit | **11,847,183** |
| Counted morning events inside the study area | **158,932** |
| Distinct morning trips across the study area | **5,768**, not the sum of LGA-specific trip counts |
| Service summary grid | **248 rows**: 31 LGAs × 4 service categories × 2 windows |
| Portable release | **11 files**, loadable without raw datasets or local pipeline reports |

These checks verify the implemented transformations and the selected snapshot;
they do not establish complete GTFS certification, real-world operational accuracy
or the suitability of an area. The release CI passed with pandas deprecation
warnings; dependency compatibility remains a maintenance task. The test count is
a record for this code snapshot, not a permanently fixed target.

## Run the packaged application locally

**No raw-data download or full pipeline rebuild is required for this path.**
Use Python **3.12** and the committed `deploy/data` directory. The commands below
are for a new checkout; an existing checkout can skip cloning.

### Windows (PowerShell or Command Prompt)

```powershell
git clone https://github.com/HeomapTV123/homereach-melbourne.git
cd homereach-melbourne
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r deploy/requirements.txt
.\.venv\Scripts\python.exe scripts/verify_explorer_release.py
.\.venv\Scripts\python.exe -m streamlit run deploy/streamlit_app.py --server.port 8503
```

The direct virtual-environment Python path avoids needing a PowerShell activation
script. Open the Local URL printed by Streamlit.

### macOS / Linux

```bash
git clone https://github.com/HeomapTV123/homereach-melbourne.git
cd homereach-melbourne
python3.12 -m venv .venv
.venv/bin/python -m pip install -r deploy/requirements.txt
.venv/bin/python scripts/verify_explorer_release.py
.venv/bin/python -m streamlit run deploy/streamlit_app.py --server.port 8503
```

The standalone verifier should report **31 comparison LGAs**, **3,286 rental
history rows** and **11 verified release files**, with no local pipeline reports
or raw datasets read. Keep `deploy/.gitattributes`: its data-file rule preserves
byte-specific fingerprints across operating systems. Investigate integrity
errors; do not edit hashes to suppress them.

### Three separate application entry points

| Entry point | Purpose | Requirements |
|---|---|---|
| `deploy/streamlit_app.py` | Portable frozen release; the hosted application | Serving dependencies and committed `deploy/data` |
| `app/Explore.py` | Local real-data explorer | Completed local explorer bundle and upstream build reports |
| `app/Home.py` | Original synthetic demonstration | Fictional sample inputs; not the real-data release |

## Develop or reproduce the pipelines

Use the full development environment for GIS processing, notebook work and the
complete test suite. Do not recreate an already-working `homereach` environment.

```bash
# From the repository root; create the environment only on a new setup.
conda env create -f environment.yml
conda activate homereach
python -m pytest -o "addopts=" -q
```

The development environment installs the local package in editable mode. A fresh
checkout can run the synthetic tests without the official raw archives. Full
source reconstruction requires the **exact audited snapshots**, not whatever
newer files a publisher currently distributes.

Retain the original filenames and put them at:

```text
data/raw/rent/quarterly-median-rents-local-government-area-september-quarter-2025-excel.xlsx
data/raw/geography/LGA_2025_AUST_GDA2020.zip
data/raw/transport/gtfs.zip
```

Follow the source-audit notes and configuration before running these jobs in order:

```bash
python scripts/build_rent_panel.py --update-registry
python scripts/build_lga_geography.py --update-registry
python scripts/build_transport.py --update-registry
python scripts/build_explorer_data.py
```

The notebooks document how the methods were established; the reusable jobs
perform the builds. Existing notebook exports are compared when available, with
missing references reported rather than invented. Configuration pins source
fingerprints and scope; a different archive requires a new audit. Do not change
an expected fingerprint or delete previous exports merely to pass a check.

Packaging a **reviewed local bundle** is a separate step:

```bash
python scripts/package_explorer.py --check-only
python scripts/package_explorer.py
python scripts/verify_explorer_release.py
```

An identical packaged release is preserved. A changed existing release stops for
review; this is not a general automatic-update command. See the
[deployment guide](docs/explorer_deployment.md) before replacing published data.
The original sources, most intermediate/processed outputs and credentials must
not be force-added to Git. `deploy/data` is the deliberate publication exception.

## Repository guide

| Location | Role |
|---|---|
| `notebooks/01`–`08` | Source audits, rental EDA, maps, GTFS analysis and combined EDA |
| `src/homereach/io`, `geography`, `transport` | Reusable source preparation and geographic/service validation |
| `src/homereach/explorer` | Comparison logic, bundle validation, charts, local UI and release loading |
| `scripts/` | Reproducible builders and package/release-verification commands |
| `config/` | Audited snapshot settings and explicit name aliases |
| `deploy/` | Hosting entry point, serving dependencies, attribution and packaged data |
| `tests/` | Unit/integration checks and Streamlit AppTest interactions |
| `docs/` | Methods, source registry, implementation guides and release evidence |

Start with the [real-data explorer guide](docs/real_data_explorer.md),
[deployment guide](docs/explorer_deployment.md),
[combined EDA findings](docs/transport_rent_eda.md) and
[data registry](docs/data_registry.csv).

## Interpretation boundaries

Rent values are historical nominal area medians, not live listings, fixed-property
histories or household-income affordability estimates. LGA medians must not be
averaged to manufacture a metropolitan median.

Transport indicators measure scheduled stop-record visits and distinct contributing
trip IDs for one date. They are not riders, vehicles, capacity, actual punctuality,
regular headways, waiting times or destination-specific commute times. Trips can
serve several LGAs; adding LGA distinct-trip counts double-counts them.

The selected feeds do not include every transport operation. LGA size, stop
placement and repeated/co-located source records affect counts. A stop outside a
polygon may serve residents inside it; point-in-polygon membership is not a
walking catchment. Unknown accessibility fields are not treated as inaccessible.
ABS statistical boundaries are not legal boundary definitions.

The newer transport snapshot is not backfilled into historical rental-model
validation. The release does not fetch newer rents or timetables automatically,
and contains **no combined suitability score, forecast or recommendation**.

## Future work — not implemented in this release

Possible next research stages are chronological rental forecasting against a
seasonal-naive baseline, destination-based routing and better-justified access
measures, and a reviewed snapshot-refresh process. These require their own data,
validation and interpretation work before entering the deployed application.
Dependency maintenance and usability improvements remain separate engineering work.

## Sources, attribution and project ownership

Source publishers are **Homes Victoria / DFFH**, **Transport Victoria / Department
of Transport and Planning**, and the **Australian Bureau of Statistics**. Dataset
attribution, source links, licence evidence and transformations are documented in
[deploy/DATA_SOURCES.md](deploy/DATA_SOURCES.md) and the public
[source-attribution record](deploy/data/source_attribution.json).

The source-data licence statements are not a licence for HomeReach's application
code. This documentation update does not add or change a source-code licence.
This is an independent student project; no publisher endorsement is implied.

Maintained by [HeomapTV123](https://github.com/HeomapTV123). Project issues and
reproducible bug reports can be recorded in the repository's Issues tab. Do not
post credentials, personal records or raw private data in an issue.
