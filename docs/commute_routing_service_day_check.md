# Fictional service-day compatibility experiment

## Result and decision

The pinned engine misses four expected previous-service-day trips in the
Linux experiment. The ordinary Tuesday and Wednesday services, same-day calendar
addition/removal controls, and a Tuesday trip crossing midnight behave as
expected. This isolates a service-day compatibility problem after the successful
[Windows source-timetable audit](commute_gtfs_timetable_audit.md).

The maintainer supplied both the Windows terminal summary and the complete JSON
on **23 November 2026**. The [raw Windows
report](evidence/routing_service_day_windows_2026-11-23.json), [checkpoint
record](evidence/routing_service_day_windows_checkpoint_2026-11-23.json) and
[platform comparison](evidence/routing_service_day_platform_comparison_2026-11-23.json)
confirm the same twelve case outcomes and exactly four missing-itinerary
findings. Execution-source and fixture hashes match; runtime versions differ.
Every raw query-row field matches except a **1.7462298274040222e-10 metre**
difference in each of the 174 BUS distance values. Those raw values are preserved.

The [complete native report](evidence/routing_service_day_linux_2026-11-22.json)
records **12 completed BUS queries**, one independent walking control,
**4 of 8 positive cases passed**, and **all 4 negative controls passed**.
The command correctly reports `failed` and exits **1**. It preserves the raw
returned rows and all four missing-trip findings. No Melbourne dataset was read,
no Melbourne journey was computed, and `routing_ready` remains `false`.

The report is 849,939 bytes, SHA-256
`c2dca7b07f2a1c33e5ebc63cb8e54db2b75b286b8760c5faabc0d8d409d99dcd`.
It records the start timestamp, runtime, staged input hashes and normalized
execution-source hashes. All original and staged input checks succeeded, and the
temporary workspace was removed. These timestamp and size details describe the
Linux run; the supplied Windows report is reviewed separately below.

## Why this follows the timetable audit

The supplied Windows audit passed every selected source record: **11,847,183
rows**, including **1,311,746 active-service rows**. It found **8,430 active rows**
with an arrival or departure at or beyond `24:00:00`. The largest observed value
across all source rows was `32:47:00`; that maximum is not restricted to active
trips. Counts here refer to stop-time rows, not journeys.

GTFS encodes such events relative to a service day. For example, Tuesday
`25:05:00` represents Wednesday 01:05 in the agency's timezone. A Wednesday
request therefore needs the relevant continuation of Tuesday service, even when
Wednesday's own ordinary service is also active. The [GTFS Schedule
reference](https://gtfs.org/documentation/schedule/reference/#stop_timestxt)
documents extended service-day times. [R5py's advanced-use
guide](https://r5py.readthedocs.io/stable/user-guide/user-manual/advanced-use.html#route-with-gtfs-data-sets-that-have-trips-after-24-00-00)
reports an associated engine limitation. The experiment measures the actual
selected integration rather than treating that general description as a result
for this project.

## Fixed experiment

[`routing_service_day_fixture.py`](../scripts/routing_service_day_fixture.py)
builds a deterministic fictional GTFS ZIP with nine tables, ten routes/trips,
20 stop-time rows and explicit calendar exceptions. The existing reviewed street
grid, origin/destination points, two stops and shapes are reused. The agency
timezone is **Australia/Melbourne**, verified against the loaded native network.
Coordinates belong to the fictional grid; the timezone does not make it a
Melbourne network.

[`run_routing_service_day_test.py`](../scripts/run_routing_service_day_test.py)
starts a fresh isolated Python worker with the reviewed local R5 JAR, a **1 GiB
Java heap**, one Python routing job, a **180-second timeout**, and a private
temporary workspace outside the checkout. It reads no project raw data. The
worker validates the exact generated GTFS table bytes before loading the engine.

The existing, explicitly experimental leg-isolation and fixed-grid walking
corrections remain enabled. Their source checks, use and restoration are checked
again. No new engine correction or GTFS time transformation is applied here.
Walking distances, geometry and durations are independently checked for returned
positive itineraries. The Python audit guard limits Python file mutations and
socket operations; it is not a Java/native sandbox.

Each BUS request uses a **six-minute departure window**, walking access/egress,
one permitted public-transport ride, no automatic snapping and the R5
`max_time=20 minutes` setting. That native setting has its own profile-window
semantics; it is not presented as a measured per-sample total-duration limit.
The independent oracle checks actual returned local dates and times, exact
agency/route/stop identities, a five-minute bus ride, complete WALK/BUS/WALK
sequences, chronology, waits and the previously verified integration egress pad.
Negative controls require an empty result. There is no required alternative
count and no repair or filtering of returned itinerary clocks.

The source calendar gives ordinary service to Tuesday and Wednesday separately.
An addition activates an otherwise inactive Tuesday service; a removal cancels
an otherwise active Tuesday service. Same-day and overnight exception trips use
the same service IDs, making the daytime controls informative about exception
handling independently of previous-day continuation.

### Why the departure window is six minutes

An initial one-minute attempt exhausted the Java heap before any transit control
could complete. Source inspection explained the cause: the pinned R5 sampler
divides the window by 60 draws; a 60-second window produces a zero increment and
an indefinitely growing list. A five-minute attempt was interrupted after review
found that the sampler repeatedly rejects generated lists until it gets exactly
60 entries; that window makes acceptance very unlikely. Its owned temporary
workspace was removed after interruption.

The final six-minute window has positive increments and avoids that extreme
rejection case. The full 12-query experiment completed in **5.330 seconds** with
the original memory limit. Adjacent fictional services were spaced so a query's
expected route remains unambiguous under the native duration cutoff. These
parameter choices do not patch the engine or change the frozen real timetable.
The relevant implementation is the tagged
[R5 departure sampler](https://github.com/r5py/r5/blob/v7.5.1-r5py/src/main/java/com/conveyal/r5/profile/McRaptorSuboptimalPathProfileRouter.java),
particularly `generateDepartureTimesToSample` and its caller's exact-size loop.

## Observed cases

All query times below are local to Australia/Melbourne. `D` is Tuesday,
**13 October 2026**; `D+1` is Wednesday, **14 October 2026**. Every row is a
distinct engine request; the counts are observed alternatives, not exhaustive
departure coverage.

| Case | Query start | Expected BUS result | Linux and Windows observation |
|---|---|---|---|
| Ordinary Tuesday | D 08:00 | D 08:05–08:10 | Pass; 38 alternatives |
| Ordinary Wednesday | D+1 09:00 | D+1 09:05–09:10 | Pass; 38 alternatives |
| Same-day calendar addition | D 10:00 | D 10:05–10:10 | Pass; 38 alternatives |
| Same-day calendar removal | D 11:00 | No itinerary | Pass; empty |
| Midnight crossing | D 23:50 | D 23:58 to D+1 00:03 | Pass; 60 alternatives |
| Previous service, 24-hour time | D+1 00:10 | Tuesday `24:15–24:20`, hence Wednesday 00:15–00:20 | **Fail; missing** |
| Previous service, 25-hour time | D+1 01:00 | Tuesday `25:05–25:10`, hence Wednesday 01:05–01:10 | **Fail; missing** |
| Previous service through 32:47 | D+1 08:37 | Tuesday `32:42–32:47`, hence Wednesday 08:42–08:47 | **Fail; missing** |
| Previous service with calendar addition | D+1 02:00 | Added Tuesday `26:05–26:10`, hence Wednesday 02:05–02:10 | **Fail; missing** |
| Previous service with calendar removal | D+1 03:00 | No itinerary | Pass; empty |
| Do not wrap to the same date | D 01:00 | Tuesday `25:05` must not become Tuesday 01:05 | Pass; empty |
| Inactive later date | Thursday 15 October 01:00 | No itinerary | Pass; empty |

The positive results contain **174 alternatives / 522 transit-itinerary rows**.
All returned positive itinerary checks pass; the four failures are missing
expected services, not malformed returned journeys. The same-day exception
controls pass. The previous-day removal result alone would be weak evidence,
because an engine missing every previous-day service would also return empty.
The same-day controls address that ambiguity.

Recorded Linux runtime: Python **3.12.14**, r5py **1.1.7**, JPype **1.7.1**, OpenJDK
**21.0.13**, pandas **3.1.1**, NumPy **2.5.4** and GeoPandas **1.2.0**. The reviewed
R5 `v7.5.1-r5py` JAR has SHA-256
`d50be106cadd7b636cfc0e209052767d7df570629f79fdf98ecd5cf5d2d89be7`.
All three walking-correction scopes and the leg adapter were restored; the
adapter recorded **522 leg snapshots**. The report retains the expected inactive
date warning and the third-party Shapely deprecation warning.

## Supplied Windows report review

The supplied terminal transcript shows checkout **`3dab578`** on
`feat/commute-location-review`, execution through the existing D: routing
environment, overall status **`failed`** and exit code **1**. The subsequently
uploaded `routing-service-day-22692-22001.json` is preserved byte for byte as
[`routing_service_day_windows_2026-11-23.json`](evidence/routing_service_day_windows_2026-11-23.json).
It is **880,208 bytes**, has **30,244 CRLF line endings**, and has SHA-256
`fb89fed7237120de28f0055ac5a7ebd960df591373398bbb904a2352f54a35a7`.
An exact-path `.gitattributes` rule prevents Git line-ending conversion of this
evidence. Its twelve case diagnostics match the Linux status and option-count
pairs:

- Ordinary Tuesday, ordinary Wednesday and same-day calendar addition pass with
  **38 alternatives each**; the midnight-crossing case passes with **60**.
- `previous_service_24h`, `previous_service_25h`, `previous_service_32h` and
  `calendar_addition` fail with **0 alternatives**.
- The four negative controls pass with **0 alternatives**.
- The summary reports **inputs unchanged: `True`** and **temporary workspace
  removed: `True`**.

The full report records **12 BUS queries**, **one walking control**, **174
alternatives / 522 transit-itinerary rows**, and no query exceptions. Its complete
top-level problem list contains exactly the four missing expected itineraries;
there are no additional global problem messages. Replaying the existing parent
validator locally against each saved report reproduces both the original problem
lists and every stored case diagnostic exactly. This replay uses an in-memory
copy with the worker's pre-validation `completed` status restored; it neither
changes raw observations nor launches the engine.

All **13 normalized execution-source hashes** match Linux and the source at the
transcript's `3dab578` checkout. The fingerprint protocol normalizes CRLF to LF.
The JAR, street fixture and deterministic GTFS ZIP hashes match exactly, and
regenerating the GTFS locally reproduces its recorded hash. The raw JSON does not
embed a Git commit: the checkout association comes from the transcript and the
matching source hashes.

The 522 transit rows contain 174 BUS legs and 348 walking legs. Every query
setting, row identity, sample ordering, clock, wait, duration and geometry agrees
between platforms. The only differing row field is each BUS `distance_m`:
**2674.2445432960913** on Windows versus **2674.2445432959166** on Linux. The
independent walking control is exactly equal. This is a measured numerical
difference, not byte-for-byte report or environment equivalence.

| Runtime component | Windows | Linux |
|---|---|---|
| Python | 3.12.16 | 3.12.14 |
| Embedded Java | 21.0.10 | 21.0.13 |
| pandas | 3.0.3 | 3.1.1 |
| NumPy | 2.3.5 | 2.5.4 |
| r5py / JPype | 1.1.7 / 1.7.1 | 1.1.7 / 1.7.1 |
| GeoPandas / Shapely / pyproj / rasterio | 1.2.0 / 2.2.0 / 3.8.0 / 1.5.2 | 1.2.0 / 2.2.0 / 3.8.0 / 1.5.2 |

The Windows report's start time is **2026-11-23T11:59:17.731036+00:00**, and its
recorded elapsed time is **42.813 seconds**. These are report values; the assistant
did not execute or independently time the original Windows run. Comparing this
elapsed time with Linux's 5.330 seconds is not a controlled performance benchmark.

The embedded JVM started with the reviewed JAR, the 1 GiB heap limit and one
routing job. All walking scopes and the leg adapter were restored; 522 leg
snapshots were recorded. The native graph and protected inputs remained unchanged,
and cleanup succeeded. The nested `runtime_inventory` is the preflight captured
before engine initialization, so its `embedded_jvm_started: false` is consistent
with the later worker's `engine.jvm_started: true`. The two recorded warnings
(inactive service date and the Shapely deprecation) are identical across platforms.

The complete Windows baseline is now reviewed. No rerun of this unchanged
experiment is needed. The [source-selection
review](commute_service_day_selection_review.md) describes the next controlled
service-date investigation; this baseline remains failed and `routing_ready`
remains `false`.

## Reproduce on Windows

The command below is retained for future reproduction. The maintainer has
already supplied the full report reviewed above. Use the existing routing
environment and reviewed JAR; the completed real timetable audit does not need
to be repeated. In Anaconda Command Prompt:

```bat
cd /d "D:\My project\homereach_melbourne"
git switch feat/commute-location-review
git pull --ff-only origin feat/commute-location-review

set "HOMEREACH_SERVICE_DAY_REPORT=D:\homereach-conda\tmp\routing-service-day-%RANDOM%-%RANDOM%.json"
conda run --no-capture-output --prefix "D:\homereach-conda\envs\homereach-routing" python -B scripts/run_routing_service_day_test.py --jar "D:\homereach-conda\r5-engine\r5-v7.5.1-r5py-all.jar" --work-root "D:\homereach-conda\tmp" --json > "%HOMEREACH_SERVICE_DAY_REPORT%"
echo Exit code: %ERRORLEVEL%
echo Report saved at: "%HOMEREACH_SERVICE_DAY_REPORT%"
```

This saves the full report outside the repository. Inspect or share that JSON;
it contains the per-case results and original returned rows. The default command
without `--json` instead prints a short per-case summary.

The expected reproduction pattern is overall `failed`, exit **1**, all twelve
queries completed, the four previous-service positive cases missing, all other
cases passing, inputs unchanged and cleanup successful. An unavailable runtime
or rejected prerequisite instead reports `blocked` with exit **2**. Only a
complete passing compatibility experiment returns **0**. A timeout, exception or
failed control is a different finding and must not be described as reproduction
of the observed overnight behaviour.

## Validation and remaining scope

The two focused regression modules pass **172 tests in 1.66 seconds**. The full
project suite passes **1,265 tests in 21.96 seconds**, with no skips, in the Linux
pandas compatibility environment and third-party pytest autoload disabled.
Those automated checks validate the fixture, independent oracle, failure
reporting, process boundaries, input preservation and cleanup. The native engine
experiment above is a separate recorded run and correctly fails its new gate.

This experiment establishes the described failure for the selected integration
and fictional timetable. It does not evaluate every R5 API, approve an engine
upgrade, certify all sampled alternatives, or validate real Melbourne streets,
transfers, entrances, accessibility, DST transitions or observed travel times.
The [departure-sampling limitation](commute_routing_departure_sampling.md) and
fixed-grid correction boundary remain relevant.

The next decision is an explicitly reviewed engine/integration approach that
preserves service-day meaning. Any candidate must pass these controls, the
earlier timing/geometry checks and independent source-calendar comparisons.
Preserve the original GTFS archive and its audit evidence while evaluating that
approach; no rewritten timetable or production routing claim is approved here.
