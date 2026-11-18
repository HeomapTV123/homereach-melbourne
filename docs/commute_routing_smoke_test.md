# Synthetic routing engine smoke test

## Checkpoint — itinerary validation is blocked

The Windows environment passed the [runtime prerequisite inventory](commute_routing_runtime.md). That result covers interpreter/package metadata and `java -version`; it does not establish that the embedded engine works on Windows.

A separate Linux experiment exercised native imports, the embedded Java 21 JVM, the pinned R5 engine, a fictional street network and three routing queries. Walking returned an itinerary, the active date returned actual bus legs, and the inactive date returned no bus itinerary. **The detailed transit results failed chronology checks: some buses depart before their preceding walking leg arrives, and reported waiting times disagree with those arrivals. The Melbourne routing pilot remains blocked.**

The [captured Linux report](evidence/routing_smoke_linux_2026-11-18.json) records the runtime inventory, engine identity, returned legs, validation failures and cleanup outcome. Its counts describe that run; they are not fixed expected outputs. Linux evidence does not establish the result of a Windows engine run.

[`scripts/run_routing_smoke_test.py`](../scripts/run_routing_smoke_test.py) is a reusable diagnostic that reports this failure. It preserves returned leg values in its JSON output and checks them without rewriting timestamps or dropping failing alternatives.

## Fixed experiment and execution limits

The [fixture generator](../scripts/routing_smoke_fixture.py) defines a fictional 7-by-7 street grid near longitude/latitude `(0, 0)`: 49 nodes, 84 two-node residential ways, explicit walking access and no one-way restriction. These coordinates and services have no Melbourne meaning.

The committed [OSM XML](../tests/fixtures/routing_smoke/streets.osm) is the reviewed source for the [small PBF](../tests/fixtures/routing_smoke/streets.osm.pbf), converted with PyOsmium 4.3.2 during fixture preparation. Running the diagnostic uses that PBF directly; it requires no Osmium installation or new package installation in the existing routing environment. The GTFS ZIP is generated deterministically using Python's standard library.

| Query | Fixed input | Required evidence |
| --- | --- | --- |
| Walking | 13 October 2026, 08:00 UTC | Positive finite distance/duration and nonempty walking geometry for the specified pair. |
| Active bus service | Same date/time; bus as the main mode with walking access/egress | Actual `SMOKE_BUS` legs between `SMOKE_WEST` and `SMOKE_EAST`, timetable-consistent departures and five-minute rides, plus consistent leg chronology and waits. |
| Inactive bus service | 14 October 2026, 08:00 UTC | No itinerary: this date is inside the feed calendar range but has no scheduled service. |

The fictional agency timezone is `Etc/UTC`. Tuesday service has three departures at 08:05, 08:10 and 08:15, each with a five-minute ride. Each query uses a ten-minute departure window, a 90-minute travel/walking limit, walking speed 3.6 km/h and at most one public-transport ride. Coordinate snapping is disabled. These are fixture settings, not estimated Melbourne journey parameters.

The parent checks installed prerequisites and the local engine/PBF fingerprints before starting the worker. It creates a fresh temporary directory under the supplied `--work-root`, copies the reviewed inputs there, and starts an isolated Python worker with a 180-second timeout. The worker uses a 1 GiB Java heap ceiling and one Python routing job. The heap ceiling is not a total-process RAM limit; Python, native libraries and JVM overhead require additional memory, and this setting does not limit every native thread.

The worker sets the explicit local R5 classpath, heap and temporary directory before importing r5py. It avoids default configuration files using the ConfigArgParse singleton reused by this pinned r5py version. Fresh per-run configuration, cache and temporary directories prevent the experiment from reusing user cache contents. Inherited Java option/classpath overrides are excluded. The runner performs no engine or dataset download.

A Python audit hook rejects Python filesystem mutations outside the temporary workspace and Python socket connection/name-resolution operations. **This hook is not a Java/native sandbox.** It provides protection against incidental Python-side effects, including r5py's global configuration-template attempt; it does not prove that every native filesystem or network operation is intercepted. The worker imports rasterio as well as the routing stack to exercise the installed native dependency.

Temporary engine/cache files are expected during execution. The parent removes its temporary workspace after completion and reports whether cleanup succeeded. The runner does not write its final report into the checkout; `--json` prints the complete report to standard output for explicit capture.

## Engine and fixture provenance

The selected engine is the compatible binary pinned in [r5py 1.1.7's classpath source](https://github.com/r5py/r5py/blob/v1.1.7/src/r5py/util/classpath.py), published in the [R5 v7.5.1-r5py release](https://github.com/r5py/r5/releases/tag/v7.5.1-r5py).

| Input | Size / SHA-256 |
| --- | --- |
| `r5-v7.5.1-r5py-all.jar` | 64,437,972 bytes; `d50be106cadd7b636cfc0e209052767d7df570629f79fdf98ecd5cf5d2d89be7` |
| `streets.osm` | `d6244955cb3a5e85fce78833749350bce47cf657b963374c74eb23ab78c64f3c` |
| `streets.osm.pbf` | `5d8eee5ad473e362142887d9ea41f135d804b6d1fba42576e9a66fc56cf12879` |

The runner enforces the JAR size/hash and PBF hash before loading them, checks their copied versions, and records the generated GTFS ZIP hash. Unit tests compare the committed XML with the generator. Recreating a PBF with another writer/version can change its bytes and requires an explicit fixture review and fingerprint update.

## Why the current engine result fails

In [the pinned `TripPlanner.transit_paths` implementation](https://github.com/r5py/r5py/blob/v1.1.7/src/r5py/r5/trip_planner.py), access and egress leg objects are cached by stop. Each alternative retrieves the cached object and changes its departure/arrival timestamps. [`TripLeg.__add__`](https://github.com/r5py/r5py/blob/v1.1.7/src/r5py/r5/trip_leg.py) adds that same object to a trip by reference. [`DetailedItineraries`](https://github.com/r5py/r5py/blob/v1.1.7/src/r5py/r5/detailed_itineraries.py) serializes the trips after the alternatives have been constructed. Later alternatives can therefore overwrite timestamps retained by earlier alternatives. This source mechanism is consistent with the shared access/egress timestamps and chronology failures in the captured run.

The validator checks ordered segments, valid timestamps, positive finite durations, nonnegative waits and that each leg starts after the previous leg arrives. For this one-bus fixture it also compares bus waiting time with the gap after the access leg. It does not require every adjacent leg to meet at exactly the same time: the pinned implementation deliberately adds one minute before the egress leg.

Upstream [issue #417](https://github.com/r5py/r5py/issues/417) describes matching departure/wait inconsistencies. It was closed on 20 March 2026 after the maintainer could not reproduce the old example and the reporter no longer had the project available; the closure does not identify a fix. [PR #411](https://github.com/r5py/r5py/pull/411) introduced caching of access/egress/transfer legs. No upstream issue or comment has been posted for this project.

No public copy/no-cache option was found in the pinned API. A reviewed correction and a repeat of the unchanged diagnostic are needed before trusting detailed journey timelines. Aggregate matrix results alone cannot establish detailed itinerary chronology. The present result does not validate Melbourne street/GTFS compatibility, public station entrances, transfers, paid barriers, accessibility or actual travel times.

## Optional Windows reproduction in the existing environment

The Linux failure is already sufficient to block the next pilot stage. A Windows reproduction can establish whether the same symptom occurs in the maintainer's existing environment; no environment rebuild is needed. Use Anaconda Prompt / CMD:

```bat
cd /d "D:\My project\homereach_melbourne"
git switch feat/commute-location-review
git pull --ff-only origin feat/commute-location-review
if not exist "D:\homereach-conda\r5-engine" mkdir "D:\homereach-conda\r5-engine"
if not exist "D:\homereach-conda\tmp" mkdir "D:\homereach-conda\tmp"
```

If the fixed JAR is already present, skip the download and let the runner verify it. Otherwise this explicit preparation command downloads only the reviewed release asset (about 64.4 MB). Exclusive creation with `xb` prevents overwriting an existing file:

```bat
conda run --no-capture-output --prefix "D:\homereach-conda\envs\homereach-routing" python -B -c "from pathlib import Path; import shutil,urllib.request; p=Path(r'D:\homereach-conda\r5-engine\r5-v7.5.1-r5py-all.jar'); output=p.open('xb'); source=urllib.request.urlopen('https://github.com/r5py/r5/releases/download/v7.5.1-r5py/r5-v7.5.1-r5py-all.jar',timeout=60); shutil.copyfileobj(source,output); output.close(); source.close(); print('Downloaded:',p)"
```

The diagnostic refuses an incomplete or different JAR before import. A failed download can leave a partial file; preserve/rename that specific file before retrying its download. The diagnostic itself does not fetch a replacement.

```bat
conda run --no-capture-output --prefix "D:\homereach-conda\envs\homereach-routing" python -B scripts/run_routing_smoke_test.py --jar "D:\homereach-conda\r5-engine\r5-v7.5.1-r5py-all.jar" --work-root "D:\homereach-conda\tmp"
echo Exit code: %ERRORLEVEL%
```

For a retained JSON report, use the same command with `--json` and capture standard output to a new file outside the checkout:

```bat
set "HOMEREACH_SMOKE_REPORT=D:\homereach-conda\tmp\routing-smoke-%RANDOM%-%RANDOM%.json"
conda run --no-capture-output --prefix "D:\homereach-conda\envs\homereach-routing" python -B scripts/run_routing_smoke_test.py --jar "D:\homereach-conda\r5-engine\r5-v7.5.1-r5py-all.jar" --work-root "D:\homereach-conda\tmp" --json > "%HOMEREACH_SMOKE_REPORT%"
echo Exit code: %ERRORLEVEL%
type "%HOMEREACH_SMOKE_REPORT%"
```

| Status | Exit code | Meaning |
| --- | --- | --- |
| `PASSED` | 0 | Every runtime, fixture, routing and timeline assertion passed in this run. |
| `BLOCKED` | 2 | Prerequisites, local inputs or work-directory checks prevented the engine experiment. |
| `FAILED` | 1 | Engine execution or result validation failed; inspect `problems`, timeline counts and worker log tail. |

`FAILED` with chronology/wait errors is consistent with the known Linux result. A completed worker and three attempted queries do not turn that result into a pass. Conda may add its generic failed-command message; retain the diagnostic's detailed report.

## Ordinary regression tests

The fixture and runner tests use the standard test environment. They require no r5py installation, R5 JAR, embedded JVM or real routing datasets, and ordinary CI does not launch the engine:

```bat
conda run --no-capture-output -n homereach python -m pytest -o "addopts=" -q tests/test_routing_smoke_fixture.py tests/test_routing_smoke_test.py
```

These tests cover fixture references/calendar semantics, guard/cleanup behavior, input fingerprints and validation of both valid and contradictory returned legs. The separate native experiment supplies the actual engine evidence. The next technical checkpoint is a reviewed resolution of the itinerary-timing defect followed by the same fixture checks; Melbourne routing remains pending that result and its separate input/access validation.
