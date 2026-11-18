# Synthetic routing engine smoke test

## Checkpoint — Windows timing passes; walking accuracy check fails

The explicit `--isolate-itinerary-legs` adapter passes the unchanged fixture's timing and integration checks on Linux and Windows. The [corrected Linux report](evidence/routing_smoke_isolated_linux_2026-11-18.json) records 60 complete transit alternatives, zero chronology overlaps, zero bus-wait mismatches and zero incorrect egress gaps. The adapter copied 180 legs, restored the original method, and the temporary workspace was removed. That run completed in 11.407 seconds.

The maintainer's [supplied Windows checkpoint from `73543a8`](evidence/routing_smoke_windows_checkpoint_2026-11-18.json) records the same zero timing/sequence failure counts across 60 alternatives, 180 leg snapshots, restoration of the original method, three completed queries, successful cleanup and exit code 0. This is recorded console evidence; a complete Windows raw-leg JSON report was not supplied.

**The next, independent walking-accuracy check fails on Linux with the timing adapter enabled.** The optional `--check-walking-geometry` mode captures raw GeoJSON and CRS and compares the walking legs with an oracle built from the committed OSM XML. The fixture, engine and query settings remain unchanged. Its [separate report](evidence/routing_walk_geometry_linux_2026-11-18.json) records 121 walking legs, 121 endpoint mismatches, 121 disagreements between geometry length and reported distance, 61 reported-shortest-distance mismatches and 121 paths extending outside the direct reference walking path, with zero malformed legs. Timing and single-bus checks still have zero failures. See the [walking-geometry investigation](commute_routing_geometry_check.md) for the confirmed reverse-search cost defect, the separate whole-edge geometry issue and the next engineering step. Melbourne routing remains pending these corrections and its own input/access checks.

The original upstream behavior remains reproducible. The [earlier failed Linux report](evidence/routing_smoke_linux_2026-11-18.json) is preserved. The maintainer's supplied Windows terminal output from checkout `c03cb4a` also reports a started JVM, three attempted queries and the same 23 overlaps and 59 bus-wait mismatches across 60 alternatives. It exits with code 1 and reports successful temporary cleanup. This earlier run records the unmodified behavior; the later `73543a8` checkpoint records the timing adapter's success.

A fresh [Linux upstream control](evidence/routing_smoke_upstream_control_linux_2026-11-18.json) using the strengthened checker also failed: 23 overlaps, 59 bus-wait mismatches and 53 incorrect egress gaps across 60 options. Its raw rows are retained separately from the corrected run. The [paired comparison](evidence/routing_smoke_leg_isolation_comparison_2026-11-18.json) records the before-and-after checks.

The fresh upstream rows exactly match the historical failure. The corrected run retains the same option/segment order and every captured field except 112 walking departure timestamps: 59 access and 53 egress. Every BUS row is identical, as are the direct walking result, empty inactive-service result and input fingerprints. The reports capture geometry presence rather than coordinates, so this comparison does not independently establish identical geometry coordinates.

| Observation | Earlier Linux upstream run | Supplied Windows upstream run | Linux with leg isolation | Supplied Windows with leg isolation |
| --- | ---: | ---: | ---: | ---: |
| Transit alternatives returned | 60 | 60 | 60 | 60 |
| Chronology overlaps | 23 | 23 | 0 | 0 |
| Bus-wait mismatches | 59 | 59 | 0 | 0 |
| Incorrect egress padding | 53, checked from preserved raw legs | Not measured by that runner version | 0 | 0 |
| Timing/integration result | Failed | Failed | Passed | Passed |

These are observed counts, not required alternative counts. This table describes the historical timing/integration checks; those runs did not include the later geometry oracle. [`scripts/run_routing_smoke_test.py`](../scripts/run_routing_smoke_test.py) retains its default unmodified-upstream mode. The correction is an explicit, experimental integration option confined to its fresh worker. Both modes retain all returned leg rows and validate them without rewriting timestamps or dropping failing alternatives.

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

## Cause of the upstream failure

In [the pinned `TripPlanner.transit_paths` implementation](https://github.com/r5py/r5py/blob/v1.1.7/src/r5py/r5/trip_planner.py), access and egress leg objects are cached by stop. Each alternative retrieves the cached object and changes its departure/arrival timestamps. [`TripLeg.__add__`](https://github.com/r5py/r5py/blob/v1.1.7/src/r5py/r5/trip_leg.py) adds that same object to a trip by reference. [`DetailedItineraries`](https://github.com/r5py/r5py/blob/v1.1.7/src/r5py/r5/detailed_itineraries.py) serializes the trips after the alternatives have been constructed. Later alternatives can therefore overwrite timestamps retained by earlier alternatives. This source mechanism is consistent with the shared access/egress timestamps and chronology failures in the captured run.

The validator retains its checks for ordered segments, valid timestamps, positive finite durations, nonnegative waits and nonoverlapping leg chronology. For this one-bus fixture it also compares bus waiting time with the gap after the access leg.

A separate fixture check now requires every option to contain the complete `WALK → BUS → WALK` sequence and the final walk to depart 60 seconds after its own bus arrives, with at most one second of rounding tolerance. This preserves the pinned implementation's deliberate egress padding; it is not a universal journey rule. The extra check matters because a shared egress leg can acquire a later timestamp without causing an overlap. In the preserved failed Linux report, 53 options have the wrong egress gap even though that defect alone would pass a monotonicity check.

Upstream [issue #417](https://github.com/r5py/r5py/issues/417) describes matching departure/wait inconsistencies. It was closed on 20 March 2026 after the maintainer could not reproduce the old example and the reporter no longer had the project available; the closure does not identify a fix. [PR #411](https://github.com/r5py/r5py/pull/411) introduced caching of access/egress/transfer legs. No upstream issue or comment has been posted for this project.

No public copy/no-cache option was found in the pinned API. The reviewed project adapter below addresses object ownership at trip assembly. Aggregate matrix results alone cannot establish detailed itinerary chronology. This fixture does not validate Melbourne street/GTFS compatibility, public station entrances, transfers, paid barriers, accessibility, complete route enumeration or actual travel times.

## Scoped leg-isolation adapter

[`scripts/routing_leg_isolation.py`](../scripts/routing_leg_isolation.py) temporarily wraps `TripLeg.__add__` during the worker's three queries. When a leg is prepended to a `Trip`, it passes `copy.copy(self)` to the original method. Each trip therefore retains its own leg state before a later alternative changes the cached object. Other addition behavior delegates unchanged. The original method is restored on normal completion and on exceptions.

This is an in-memory change scoped to the fresh worker, with one Python routing job. It does not edit the installed package or copy its route-search algorithm. The fixture, timetable, coordinates, routing parameters and raw-result validation remain in force. The shallow copy preserves the reviewed leg's concrete class and immutable scalar, date/time and Shapely 2 geometry values while giving the leg an independent attribute dictionary.

Before changing the method, the adapter requires r5py 1.1.7, one routing job, the reviewed source fingerprints for `r5/trip_leg.py`, `r5/trip_planner.py` and `r5/trip.py`, and the expected loaded method/module identities. Source hashing normalizes CRLF to LF for Windows. A different source or already modified method is refused; the integration never silently falls back to the unmodified behavior. These compatibility guards are not a security sandbox or permission to use the wrapper in a concurrent application.

The three source fingerprints were also checked against the downloaded [conda-forge r5py 1.1.7 `pyhd8ed1ab_0` package](https://conda.anaconda.org/conda-forge/noarch/r5py-1.1.7-pyhd8ed1ab_0.conda) and matched the reviewed PyPI sources. The supplied Windows run subsequently passed the source guard and timing/integration checks in the installed runtime.

The report identifies `upstream` or `isolated_legs` mode. An isolated run also records adapter name/version, verified source hashes, the snapshot count, application and restoration. The parent requires this audit to match the requested mode before accepting a pass. A pass concerns this synthetic fixture and this reviewed integration only; it does not establish that the upstream package has been fixed or that transfer itineraries work.

The independent geometry check now establishes that the final walk's 678 seconds and about 677.897 metres are inconsistent with the approximately 11.119-metre reference path. [Native R5 state evidence](evidence/routing_reverse_origin_state_linux_2026-11-18.json) shows the incorrect reverse-search starting cost before itinerary assembly; the leg-copy adapter does not change that cost. The walking geometry also includes full street edges instead of the required partial segments. The [geometry guide](commute_routing_geometry_check.md) separates these defects and records the direct, access and egress comparisons. The historical timing-only pass remains valid within its stated scope, while the expanded accuracy check correctly fails.

## Verified Windows timing checkpoint

The maintainer completed this timing/integration command successfully at `73543a8`. It remains available for reproducing that limited checkpoint in the existing D: environment with the reviewed JAR and temporary directory. Use Anaconda Prompt / CMD:

```bat
cd /d "D:\My project\homereach_melbourne"
git switch feat/commute-location-review
git pull --ff-only origin feat/commute-location-review
conda run --no-capture-output --prefix "D:\homereach-conda\envs\homereach-routing" python -B scripts/run_routing_smoke_test.py --jar "D:\homereach-conda\r5-engine\r5-v7.5.1-r5py-all.jar" --work-root "D:\homereach-conda\tmp" --isolate-itinerary-legs
echo Exit code: %ERRORLEVEL%
```

No environment rebuild, package upgrade or new JAR download is needed. Omitting `--isolate-itinerary-legs` selects the original upstream behavior, whose timing failure remains expected for the reviewed baseline.

To retain the complete JSON report, use this command instead of the preceding smoke-test command. It captures standard output to a new file outside the checkout:

```bat
set "HOMEREACH_SMOKE_REPORT=D:\homereach-conda\tmp\routing-smoke-%RANDOM%-%RANDOM%.json"
conda run --no-capture-output --prefix "D:\homereach-conda\envs\homereach-routing" python -B scripts/run_routing_smoke_test.py --jar "D:\homereach-conda\r5-engine\r5-v7.5.1-r5py-all.jar" --work-root "D:\homereach-conda\tmp" --isolate-itinerary-legs --json > "%HOMEREACH_SMOKE_REPORT%"
echo Exit code: %ERRORLEVEL%
type "%HOMEREACH_SMOKE_REPORT%"
```

| Status | Exit code | Meaning |
| --- | --- | --- |
| `PASSED` | 0 | Every assertion enabled for the selected mode passed, including walking geometry only when its flag is present. |
| `BLOCKED` | 2 | Prerequisites, local inputs or work-directory checks prevented the engine experiment. |
| `FAILED` | 1 | Engine execution or result validation failed; inspect `problems`, timeline counts and worker log tail. |

The supplied isolated Windows run has zero overlaps, wait mismatches, malformed options, unexpected leg sequences and egress-padding mismatches and confirms restoration of the original method. Future runs still need their actual results checked. If an identity/source check or any itinerary assertion fails, retain the detailed report. Conda may append its generic failed-command message. A completed worker and three attempted queries alone are insufficient for a pass.

### Optional Windows reproduction of the walking-geometry failure

The Linux geometry and native-state evidence already establishes the next engineering problem. A Windows reproduction can add platform evidence; it is not required to diagnose the defect and does not require reinstalling the environment or changing the engine. After pulling this diagnostic update, add `--check-walking-geometry` to the existing command:

```bat
conda run --no-capture-output --prefix "D:\homereach-conda\envs\homereach-routing" python -B scripts/run_routing_smoke_test.py --jar "D:\homereach-conda\r5-engine\r5-v7.5.1-r5py-all.jar" --work-root "D:\homereach-conda\tmp" --isolate-itinerary-legs --check-walking-geometry
echo Exit code: %ERRORLEVEL%
```

For the current baseline, **`FAILED` with exit code 1 is expected from the stronger accuracy checks**, even while the timing and single-bus checks stay at zero failures. This result is evidence of the walking defects, not a reason to rebuild the working environment. Append `--json` and redirect to a new report file when retaining complete raw geometries and diagnostic details. The [geometry guide](commute_routing_geometry_check.md) explains the reference paths, tolerances and repair criteria.

### Preparation for another machine

The runner accepts an existing reviewed JAR and work directory. On another machine where the fixed JAR is absent, create the parent directories and explicitly download the reviewed release asset (about 64.4 MB):

```bat
if not exist "D:\homereach-conda\r5-engine" mkdir "D:\homereach-conda\r5-engine"
if not exist "D:\homereach-conda\tmp" mkdir "D:\homereach-conda\tmp"
conda run --no-capture-output --prefix "D:\homereach-conda\envs\homereach-routing" python -B -c "from pathlib import Path; import shutil,urllib.request; p=Path(r'D:\homereach-conda\r5-engine\r5-v7.5.1-r5py-all.jar'); output=p.open('xb'); source=urllib.request.urlopen('https://github.com/r5py/r5/releases/download/v7.5.1-r5py/r5-v7.5.1-r5py-all.jar',timeout=60); shutil.copyfileobj(source,output); output.close(); source.close(); print('Downloaded:',p)"
```

Exclusive creation with `xb` prevents overwriting an existing file. The diagnostic refuses an incomplete or different JAR before import. A failed download can leave a partial file; preserve/rename that specific file before retrying its download. The diagnostic itself does not fetch a replacement.

## Ordinary regression tests

The fixture and runner tests use the standard test environment. They require no r5py installation, R5 JAR, embedded JVM or real routing datasets, and ordinary CI does not launch the engine:

```bat
conda run --no-capture-output -n homereach python -m pytest -o "addopts=" -q tests/test_routing_smoke_fixture.py tests/test_routing_smoke_test.py tests/test_routing_leg_isolation.py tests/test_routing_walk_geometry.py
```

These tests cover fixture references/calendar semantics, guard/cleanup behavior, input fingerprints and validation of both valid and contradictory returned legs. Adapter regressions reuse mutable access and egress legs across alternatives and check independent identities and retained timestamps, refusal of incompatible sources/versions, and restoration after failures. Geometry regressions exercise the independent fixture oracle and distinguish endpoint, path, distance and malformed-result failures. The earlier failed report must still fail validation. These tests require no installed routing engine; the separate native experiment supplies that evidence.

At the leg-isolation implementation checkpoint, before the walking-geometry extension, the local Linux full suite passed **832 tests in 47.24 seconds**, with no skips. Those native reports were captured before two final malformed-audit guards; revalidating their unchanged observations with that checkpoint's final parent code reproduced every saved problem and diagnostic. Those reports record the worker/adapter/fixture fingerprints at execution and the final validator fingerprint used for that recheck. This historical count does not describe the later geometry tests.

The next engineering step is to correct the reverse-search starting cost and walking-geometry construction, then rerun the unchanged fixture with both the timing adapter and independent geometry checks. Before a Melbourne development itinerary, also validate the complete GTFS timing/references and street-network compatibility, then examine walking connections and provisional station access. The completed Windows timing checkpoint does not settle those remaining questions.
