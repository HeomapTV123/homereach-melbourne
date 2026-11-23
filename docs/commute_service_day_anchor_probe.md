# Paired native service-day anchor probe

## Result and scope

The controlled Linux experiment **passes all seven pairs**. For each of the four
missing previous-service-day cases, selecting the previous service date recovers
the expected native trip. The same change excludes the valid current-day
Wednesday control. This supports the mechanism identified in the [pinned source
review](commute_service_day_selection_review.md).

The original [twelve-case compatibility diagnostic](commute_routing_service_day_check.md)
still fails on Linux and Windows. This new command has a different acceptance
contract: it checks a causal comparison between two single-date views. Its pass
does not implement combined-date routing, repair Python itinerary serialization,
or establish transfer correctness. `routing_ready` remains `false`.

## What stays fixed and what changes

Both arms use the unchanged service-day GTFS fixture, street fixture, reviewed
R5 JAR, one routing job, 1 GiB heap limit, six-minute sampling window and existing
scoped walking corrections. The worker builds one walking-cost map per pair and
passes the same maps to two fresh native transit routers.

Only the cloned native request's `date`, `fromTime` and `toTime` are changed:

| Arm for the 01:00 case | Service date | Native seconds | Derived civil interval |
|---|---|---|---|
| Current date | 2026-10-14 | 3600–3960 | Wednesday 01:00–01:06 |
| Previous date | 2026-10-13 | 90000–90360 | Wednesday 01:00–01:06 |

This derivation is valid for the fixed dates, which do not cross a daylight-saving
transition. It is not a general DST policy. Every pair must retain the same
normalized civil sampling instants, unchanged recorded non-date request fields
and unchanged access/egress maps before and after routing.

The worker reads the actual native router's active-service bitset without
changing it. It captures original services, stops and schedules before and after
the experiment, including extended timetable seconds. All final state chains and
all sampled departure keys are retained, including samples returning no path.
The native transit router is unchanged. The separately reported street-origin,
index and walking-geometry corrections remain scoped to this fictional network.

The normal Python transit itinerary serializer is never called. Counterfactual
states retain their original integer seconds and service-date association;
derived civil sample timestamps are explicitly labelled. A separate direct-WALK
control exercises and independently checks the existing walking corrections.

## Observed Linux results

The [complete report](evidence/routing_service_day_anchor_linux_2026-11-23.json)
records **14 native transit queries**, **840 samples**, **190 returned native
paths / 570 state snapshots**, and one direct walking control. Each arm retains
60 samples, and all seven pairs match their normalized civil sample times.

| Fixed case | Current-date paths | Previous-date paths | Pair outcome |
|---|---:|---:|---|
| Tuesday service at 24:15, queried Wednesday 00:10 | 0 | 38 | Passed |
| Tuesday service at 25:05, queried Wednesday 01:00 | 0 | 38 | Passed |
| Tuesday service at 32:42, queried Wednesday 08:37 | 0 | 38 | Passed |
| Added Tuesday service at 26:05, queried Wednesday 02:00 | 0 | 38 | Passed |
| Ordinary Wednesday service at 09:05 | 38 | 0 | Passed |
| Removed Tuesday service at 27:05 | 0 | 0 | Passed |
| Inactive Thursday 01:00 interval | 0 | 0 | Passed |

The counts are observations, not a fixed itinerary-count acceptance threshold or
a claim of exhaustive departure coverage. Positive arms must recover the declared
trip; negative arms must remain empty. Every retained path is checked against an
independently declared timetable and calendar oracle. Native boarding requires
strictly more than 60 seconds after access arrival; the equality boundary is
covered by a regression test.

The near-stop walking cost is 12 seconds and the other-stop cost is 2,657 seconds
in both access and egress maps, unchanged across all arms. Catalogs, original
inputs and staged inputs are unchanged. All three temporary correction scopes are
restored and the temporary workspace is removed. No query exceptions occur.

The report was recorded at **2026-11-23T12:53:49.132524+00:00** with elapsed time
**17.080 seconds** and exit code **0**. It is **502,926 bytes**, SHA-256:

```text
10a5616ef382929c6139d9067e2e7c205dbff84bbe5efcc66a9bbc643c1ef2de
```

Recorded runtime: Python **3.12.14**, r5py **1.1.7**, JPype **1.7.1**, Java
**21.0.13**, pandas **3.1.1**, NumPy **2.5.4**, GeoPandas **1.2.0**, Shapely
**2.2.0**, pyproj **3.8.0**, rasterio **1.5.2**. The R5 JAR SHA-256 and both fixture
hashes match the retained Linux and Windows baseline reports. The native run's
normalized execution-source hashes match the submitted source files. Replaying
the validators reproduces its stored pair diagnostics and empty problem list.

## Implementation and regression checks

- [Independent oracle](../scripts/routing_service_day_anchor.py): explicit service
  calendars, timetable values, fixed pairs, native-state validation and civil-time
  normalization.
- [Fresh worker](../scripts/_routing_service_day_anchor_worker.py): pinned source
  checks, shared walking costs, native request clones and immediate state capture.
- [Parent command](../scripts/run_routing_service_day_anchor_test.py): runtime and
  JAR checks, bounded subprocess, protected input/source fingerprints, report
  validation and cleanup.
- [Oracle tests](../tests/test_routing_service_day_anchor.py) and [orchestration
  tests](../tests/test_routing_service_day_anchor_test.py): missing/extra samples,
  false-positive empty results, modified clocks/identities/costs, strict boarding
  slack, malformed native states, source/runtime identities, direct walking
  geometry, nonfinite/oversized reports, timeouts, metadata conflicts, input
  mutation and cleanup failure. These tests do not launch R5.

The focused regression run passed **118 tests**. The full local suite passed
**1,383 tests in 57.11 seconds**, with no skips or warnings, using the existing
test environment with third-party pytest plugin autoload disabled. CI results
are recorded in the PR for the submitted head; they are separate from the
actual native report above.

## Run on Windows

The full Windows baseline JSON is already reviewed. Run only the new probe using
the existing D: routing environment and reviewed JAR. In Anaconda Command Prompt:

```bat
cd /d "D:\My project\homereach_melbourne"
git switch feat/commute-location-review
git pull --ff-only origin feat/commute-location-review
set "HOMEREACH_ANCHOR_REPORT=D:\homereach-conda\tmp\routing-anchor-%RANDOM%-%RANDOM%.json"
conda run --no-capture-output --prefix "D:\homereach-conda\envs\homereach-routing" python -B scripts/run_routing_service_day_anchor_test.py --jar "D:\homereach-conda\r5-engine\r5-v7.5.1-r5py-all.jar" --work-root "D:\homereach-conda\tmp" --json > "%HOMEREACH_ANCHOR_REPORT%"
echo Exit code: %ERRORLEVEL%
echo Report saved at: "%HOMEREACH_ANCHOR_REPORT%"
```

Expected: exit **0**, overall **`passed`**, **seven passing pairs**, unchanged
protected inputs and successful cleanup. An exit of 1 means a probe assertion
failed; 2 means prerequisites blocked execution. Preserve and review the complete
JSON in either case. A supplied Windows probe report is still pending.

## Remaining integration decision

The experiment demonstrates both the recovery and loss caused by selecting a
different service day. A general solution must retain relevant service instances
on one coherent time axis, preserve calendar exceptions and trip identities, and
allow transfers between previous-day and current-day services. Joining completed
answers from independent single-date runs cannot establish such a transfer.

The next decision must be tested against mixed-service-day transfers, overlapping
services, midnight-spanning query windows, date boundaries, DST and the complete
range of source times. The native experiment adds no timetable transformation or
production adapter. The original timetable audit and failed compatibility
baseline remain preserved; no real Melbourne journey or travel-time estimate is
produced by this command.
