# Scheduled commute pilot: input preparation

## Purpose and current boundary

The next feature supports the project charter's renter who has a weekly rent
budget and a maximum commute preference. The first experiment will estimate
scheduled public-transport journeys from a small set of documented public origin
points to one destination. The proposed demonstration destination is a reviewed
public entrance to Flinders Street Station; its exact coordinates and the origin
sample still need source checks. These points will illustrate journeys, rather
than represent all residents or rental properties in an LGA.

This change implements **input preflight only**. It checks the existing audited
timetable, reports missing prerequisites, and adds regression tests using small
fictional feeds. It produces no journey times, suitability scores or app output.
No real Melbourne journey has been calculated or validated at this checkpoint.

## Fixed timetable context

`config/routing_pilot.json` references the existing `config/gtfs_snapshot.json`.
The preflight and transport pipeline share the pinned validator in
`homereach.transport.snapshot`; editing that source fingerprint or its audited
counts is rejected. The pipeline continues to expose the original import name.

| Setting | Pilot value |
| --- | --- |
| Archive | `data/raw/transport/gtfs.zip` |
| SHA-256 | `c88af3abcaf0872e45196dcc1d5af9bc20a82c54a00a9dfef46c809ec2e34814` |
| Local service date | 13 October 2026 |
| Timezone | `Australia/Melbourne` |
| Selected nested feeds | `2/google_transit.zip`, `3/google_transit.zip`, `4/google_transit.zip` |
| Active trips after calendar exceptions | Train: 2,828; tram: 5,044; Myki bus: 27,708 |
| Proposed departure anchors | 07:00, 07:30, 08:00 and 08:30 |
| Street-network provenance | Unconfigured |
| Verified origin/destination coordinates | Unconfigured |

The departure anchors are experiment inputs, not a complete routing-parameter
specification. Before computing travel-time matrices, choose the departure
sampling window and statistic explicitly. R5py aggregates minute-by-minute
departures over a window, and its documentation warns that short windows can
miss journeys on infrequent services. See the official
[travel-time matrix guide](https://r5py.readthedocs.io/stable/user-guide/user-manual/travel-time-matrices.html).

## Run the preflight

From this repository in the existing `homereach` environment:

```text
python scripts/check_routing_inputs.py
```

For machine-readable output:

```text
python scripts/check_routing_inputs.py --json
```

To select the existing environment explicitly from PowerShell or Command Prompt:

```text
conda run --no-capture-output -n homereach python scripts/check_routing_inputs.py
```

This invokes Python from the named environment without relying on the current
shell's activation state. If `conda` is unavailable in that terminal, use the
Anaconda Prompt from the existing installation. The
[Conda command reference](https://docs.conda.io/projects/conda/en/stable/commands/run.html)
documents environment selection and live output.

The preflight uses pandas/NumPy and does not import GeoPandas, Pyogrio, PyProj,
Shapely or a routing/JVM runtime. Full spatial builds still need the geospatial
packages in `environment.yml`. If pandas or NumPy is missing,
the CLI reports an environment error with the interpreter path and an explicit
environment command. It does not inspect or classify the GTFS archive in that
case. Missing project modules still raise their original exception so checkout
or programming defects are not hidden. Other import failures retain their
original error.

`--project-root` can point at another checkout containing the pilot configuration
and original archive. Paths inside the configuration must stay within that
project root. The command does not download an archive, replace source files,
extract feed files into the project, or rebuild geographic/transport outputs.
The existing ZIP helper may spool large nested archives to the operating system's
temporary directory and cleans them up after use.

### Interpreting the result

- **GTFS verified; routing blocked:** the present archive matches the pinned
  fingerprint, archive inventory, small-table checks and active-trip counts.
  Street-network provenance, locations and the routing experiment still need
  implementation and review.
- **GTFS missing; routing blocked:** the original archive is absent from the
  reported path. Restore the already-audited local archive there; a newly
  downloaded feed may describe a different date and have a different hash.
- **Error:** configuration or a present archive violates the input contract.
  Inspect the reported cause and preserve the original data. A different feed
  needs its own reviewed snapshot rather than an edited expected fingerprint.
- **Environment error:** the selected Python interpreter cannot import a required
  external dependency. Use the existing project environment and rerun the
  command; no conclusion about the data has been reached.

Exit code **2** means prerequisites are still blocked. This is expected at this
input-preparation stage, including when the timetable checks succeed. Exit code
**1** means an invalid configuration, an invalid/unreadable present input, or a
missing Python dependency. JSON distinguishes `invalid` from `environment_error`.
There is no successful-routing exit code in this implementation.

The report separates completed checks from prerequisites and validations that
have not been performed. In particular, reading `stop_times.txt` headers does
**not** validate all its rows, timings, references or transfers. Matching an
archive hash and calendar counts does not establish network connectivity or a
working journey. The preflight does not start Java or import R5py.

## Preserve complete routing inputs

Keep identifiers scoped by feed. Identical stop or trip IDs in two feeds can
represent different objects. Preserve complete trips, terminal stops, transfer
information and relevant stops outside the study LGAs. The LGA service-count
outputs exclude records for their own statistical definitions and are not
substitutes for a routing timetable.

The inherited reader rejects `frequencies.txt`. Supporting frequency-based
service requires a reviewed extension. Calendar additions and removals are
applied using the existing tested service-selection helpers.

## Next implementation gate

1. Run the preflight against the original local archive and retain its output.
2. Obtain a suitable OSM `.pbf` extract; record source URL, download date, data
   timestamp, coverage, license/attribution and the actual file's SHA-256.
   Preserve enough surrounding network for access, transfers and complete
   journeys. A modern street snapshot combined with the historical timetable
   must be described as a mixed-vintage experiment.
3. Record one verified destination entrance and a small origin sample with IDs,
   source coordinates, CRS and a stated selection method. Check points and
   walking connections on a map before interpreting results.
4. Validate the separate routing runtime and record resolved package, Java and
   engine versions. Choose memory settings, walking rules, transfer limits,
   departure windows, journey-duration limits and snap behavior explicitly.
5. Calculate a small set of journeys and inspect example itineraries. Retain
   unreachable results, test departure-time sensitivity and distinguish
   scheduled estimates from observed punctuality.

Only then should a reusable routing runner, its regression fixtures and an
explorer integration be proposed. The current `null` street-network/location
fields are deliberate; non-null configurations need an implementation that
actually validates those inputs.

R5py requires an OSM street network for walking access, egress and transfers as
well as GTFS for scheduled transit. Its official installation guide recommends
a separate conda environment on Windows and requires JDK 21 or later. The
existing `environment-routing.yml` is a starting specification, not evidence
that this runtime has been installed or exercised. Sources:
[data requirements](https://r5py.readthedocs.io/stable/user-guide/user-manual/data-requirements.html)
and [installation](https://r5py.readthedocs.io/stable/user-guide/installation/installation.html).

## Research and release continuity

The forecasting research was merged through PR #1 using merge commit
`c87857ed3ecb85377e124bed2d43373af69a3ef5`. Keep
`feat/rental-forecast-baselines` and the original local evidence for its
branch-specific replay procedure. The completed final forecasting period
remains used evaluation evidence.

This pilot runs on `feat/commute-routing-pilot`. The deployed explorer continues
to describe its rent, scheduled-service and geography snapshots. The rental
statistics are from 2025Q3; they cannot be described as contemporaneous property
prices for the October 2026 travel experiment.
