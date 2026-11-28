# Native three-stop service-day transfer baseline

## Result and purpose

The native Linux experiment on 28 November 2026 completed all eight cases. The
ordinary same-day two-bus journey passed, as did six calendar-removal and
impossible-connection controls. The required mixed Tuesday/Wednesday journey was
missing. The compatibility result is therefore **failed: seven cases passed,
one failed, process exit 1**. `routing_ready` remains `false`.

This implements the [combined-date regression contract](commute_service_day_combined_contract.md)
as a separate transit-only diagnostic. The
[paired anchor probe](commute_service_day_anchor_probe.md) had already shown that
selecting Tuesday recovers extended-time Tuesday trips while losing a Wednesday
control. The new test requires both dates within one continuous native path;
joining answers from two independent searches cannot satisfy it.

No service-day correction, timetable projection or Python transit itinerary
serialization is enabled. The original two-stop fixtures, walking corrections
and their guards are unchanged. No real project datasets are read and no
Melbourne journey or travel-time estimate is produced.

## Fixed fictional model

The fixture has stops A, B and C, one A-to-B trip and one B-to-C trip. Each case
uses a separate deterministic GTFS archive and newly built network. Query time
is Wednesday 2026-10-14 01:00:00 in `Australia/Melbourne`, with a six-minute
sampling window, sixty native samples, at most two rides and a thirty-minute
trip limit. These fixed dates do not cross a daylight-saving transition.

| Case | A-to-B service and original time | B-to-C service and original time | Required outcome |
|---|---|---|---|
| `mixed_day_transfer` | Tuesday 25:05–25:10 | Wednesday 01:15–01:20 | Two-bus path present |
| `same_day_transfer` | Wednesday 01:05–01:10 | Wednesday 01:15–01:20 | Two-bus path present |
| `mixed_remove_first` | Tuesday trip removed by exception | Wednesday 01:15–01:20 | Required chain absent |
| `mixed_remove_second` | Tuesday 25:05–25:10 | Wednesday trip removed by exception | Required chain absent |
| `mixed_impossible_connection` | Tuesday 25:05–25:10 | Wednesday 01:09–01:14 | Required chain absent |
| `same_day_remove_first` | Wednesday first trip removed | Wednesday 01:15–01:20 | Required chain absent |
| `same_day_remove_second` | Wednesday 01:05–01:10 | Wednesday second trip removed | Required chain absent |
| `same_day_impossible_connection` | Wednesday 01:05–01:10 | Wednesday 01:09–01:14 | Required chain absent |

The same-day negative cases test removals and timing against a working positive
control. The mixed-day negative cases alone could appear successful because the
first ride is already missing. GTFS `calendar_dates.txt` is omitted when a case
has no exceptions; this engine rejects a present table containing only its
header. Tests check each case's exact member inventory and raw timetable.

Access is an **artificial twelve-second cost at A only**, and egress is an
**artificial twelve-second cost at C only**. Interstop street-transfer lists are
temporarily replaced with empty lists. The original object and inventories are
restored and checked after each query, including failure paths. In the retained
run, the original inventories were already empty; the explicit scope still
ensures that the model does not acquire an unreviewed walking shortcut.

The same-stop transfer at B remains available. Both boardings must satisfy the
pinned native rule `departure > preceding arrival + 60 seconds`, so the intended
five-minute scheduled gap is feasible and the 01:09 connection is impossible.
This rule comes from the
[reviewed R5 router source](https://github.com/r5py/r5/blob/v7.5.1-r5py/src/main/java/com/conveyal/r5/profile/McRaptorSuboptimalPathProfileRouter.java).
That router's interstop-transfer expansion does not enforce `maxWalkTime`, so
setting that request option to zero would not establish this model boundary.

The reviewed fictional street file is used to construct the network. The test
does **not** establish three-stop walking connectivity, walking geometry or
duration, entrance identity, legal public access, or platform accessibility.
It invokes the unchanged native transit algorithm with an explicitly artificial
transfer model; it is not a physical walking experiment.

## Independent validation

[The fixture and oracle](../scripts/routing_service_day_transfer.py) declare
raw GTFS generation values separately from the integer timetable/calendar
expectations. The validator checks the complete native catalogs, active service
bitset, request fields, endpoint costs and before/during/after transfer tables.
Every returned chain must be access → A-to-B bus → B-to-C bus → egress, with
correct trip and stop identities, native rounds, board/alight positions, strict
boarding slack, raw schedule seconds, civil clocks and total duration.

Original service dates and expected civil times in the diagnostics are explicitly
independent sidecar expectations. They are not fields fabricated on native
states. The current-date native catalog keeps Tuesday's 25-hour times intact,
and the Wednesday request activates only Wednesday services in the mixed case.
The missing positive remains a failure; the report is not normalized into a
successful result.

All sixty sample keys per case and all returned chains are retained. A positive
case must recover a feasible declared journey, and every returned chain is
validated, including in negative cases. This is not an exhaustive departure
coverage claim and the observed path count is not an acceptance threshold. If
the same-day positive fails, the validator explicitly prohibits attributing the
mixed-day failure to date selection alone.

The [parent CLI](../scripts/run_routing_service_day_transfer_test.py) launches a
[fresh worker](../scripts/_routing_service_day_transfer_worker.py) with a
240-second timeout, a verified JAR, Java heap bounded to 1 GiB, one routing job,
finite and size-bounded JSON, and an external disposable workspace. It rechecks
the original and staged inputs plus normalized execution-source hashes, protects
parent-owned report metadata, and checks cleanup. The Python mutation/socket
guard is not a Java/native sandbox.

## Initial native Linux evidence

[Full report](evidence/routing_service_day_transfer_linux_2026-11-28.json):
**204,238 bytes**, SHA-256
`50c34f0a066495b018ca6b0d88ba859453b32d330cc667bd98fd93cee9a3a850`.
Started at `2026-11-28T13:07:32.474190+00:00`; elapsed **9.204 seconds**.

| Observed case group | Cases | Samples retained | Native paths | Result |
|---|---:|---:|---:|---|
| Mixed-day positive | 1 | 60 | 0 | Failed: required transfer missing |
| Same-day positive | 1 | 60 | 38 | Passed |
| Calendar-removal controls | 4 | 240 | 0 | Passed |
| Impossible-connection controls | 2 | 120 | 0 | Passed |

The report contains **480 samples, 38 complete native chains and 152 state
snapshots**. All eight network builds and native queries complete without query
exceptions. The sole reported problem is the missing mixed-day transfer. All
request/catalog/cost snapshots agree, each transfer-table scope restores, all
protected inputs and execution sources are unchanged, and cleanup succeeds.
Validator replay reproduces the stored diagnostics.

Runtime: Python **3.12.14**, r5py **1.1.7**, JPype **1.7.1**, Java
**21.0.13.1**, GeoPandas **1.2.0**, pandas **3.1.1**, NumPy **2.5.4**,
Shapely **2.2.0**, pyproj **3.8.0**, rasterio **1.5.2**. This is a newly restored
isolated Linux environment; it is not identical to the earlier Linux or Windows
runtime. The embedded JVM, temporary directory, classpath and 1 GiB limit were
verified. The report retains seventeen normalized execution-source fingerprints
and ten staged-input hashes: JAR, street file and eight GTFS archives. The reviewed
R5 `v7.5.1-r5py` JAR SHA-256 remains
`d50be106cadd7b636cfc0e209052767d7df570629f79fdf98ecd5cf5d2d89be7`.

The two new suites pass **195 regression tests** covering fixture members and
calendars, deterministic archives, native-chain mutations, missing positives,
unexpected negative paths, process bounds, input preservation and restoration
on error. After the shared-runner refactor below, the full local suite passes
**1,578 tests in 25.81 seconds**, with no
skips reported. These tests do not launch the native engine; the actual run
above is separate evidence. Test counts are not a measured coverage percentage.

## Shared runner and repeated native checks

The initial implementation at `03e3c4c` duplicated process and workspace
management from the original service-day command. Both parents now use
[shared diagnostic infrastructure](../scripts/routing_diagnostic_runner.py),
with explicit worker, validator, fixture-writer and source-hash callbacks. Their
scientific validators and CLI behavior are unchanged. The helper preserves
timeout/report-size bounds, finite JSON validation, protected parent metadata,
staged and original input checks, source fingerprints and cleanup. Each caller
includes the helper in its execution-source manifest.

The [transfer rerun](evidence/routing_service_day_transfer_refactored_linux_2026-11-28.json)
started at `2026-11-28T13:24:51.215870+00:00` and took **10.175 seconds**. It
contains the exact same parsed cases, sample keys, native states and diagnostics
as the initial report: **seven cases passed, mixed-day positive failed, 480
samples, 38 paths and 152 states**. All ten staged-input fingerprints match.
Its eighteen execution-source hashes match the refactored sources, and its
preservation/cleanup checks pass. File size is **204,351 bytes**, SHA-256
`e4eaf3725ffa3599af26bdcad26d54c4bfca3d32f2bdce4c4b9c1d765b891116`.

The [original twelve-case runner was also re-executed](evidence/routing_service_day_runner_refactor_linux_2026-11-28.json)
to check the other caller. It retains exactly the prior diagnostics and staged
input hashes: **eight cases pass, four previous-service-day cases fail**, with
no additional problems. It starts at `2026-11-28T13:24:51.217636+00:00`, takes
**6.412 seconds**, records fourteen execution-source hashes, and passes
preservation/cleanup checks. File size is **850,256 bytes**, SHA-256
`205e8e832c3a6e1ad11bd2cd0f3cb92b2f7cf903110d16fcd899a13b44003321`.

Both native reruns exit **1**, faithfully preserving the known compatibility
failures. Parent-validator replay reproduces both reports. All fifteen anchor
execution dependencies remain unchanged, so the reviewed Windows anchor
comparison remains valid. These runs used the runtime listed above; elapsed
times are observations, not a controlled performance comparison.

## Windows continuation

The full Windows anchor report has been reviewed and matches the earlier Linux
anchor observations. There is no need to reinstall that environment or repeat
the paired-anchor run. After updating `feat/commute-location-review`, run this
new baseline in the existing routing environment from Windows CMD:

```bat
cd /d "D:\My project\homereach_melbourne"
set "HOMEREACH_TRANSFER_REPORT=D:\homereach-conda\tmp\routing-transfer-%RANDOM%-%RANDOM%.json"
conda run --no-capture-output --prefix "D:\homereach-conda\envs\homereach-routing" python -B scripts/run_routing_service_day_transfer_test.py --jar "D:\homereach-conda\r5-engine\r5-v7.5.1-r5py-all.jar" --work-root "D:\homereach-conda\tmp" --json > "%HOMEREACH_TRANSFER_REPORT%"
echo Exit code: %ERRORLEVEL%
echo Report saved at: "%HOMEREACH_TRANSFER_REPORT%"
conda run --no-capture-output --prefix "D:\homereach-conda\envs\homereach-routing" python -B -c "import json,sys; r=json.load(open(sys.argv[1],encoding='utf-8')); print('Overall:',r['status']); print('Cases passed:',r.get('cases_passed')); print('Same-day control:',r.get('same_day_control_passed')); [print(c['id'],c['status'],'paths=',c['native_paths_checked']) for c in r.get('case_diagnostics',[])]; print('Inputs unchanged:',r.get('protected_inputs_unchanged')); print('Temporary workspace removed:',r.get('temporary_workspace_removed')); print('Problems:',r.get('problems',[]))" "%HOMEREACH_TRANSFER_REPORT%"
```

The observed Linux baseline exits **1**, with only `mixed_day_transfer` failed
and seven cases passed. A matching Windows result is evidence that the same
remaining limitation reproduces; it is not a passing compatibility result.
Preserve the full JSON for review. Any additional failures, query errors, changed
inputs, failed cleanup or a failing same-day control need separate investigation.

## Next implementation boundary

Keep the feature PR in draft. The next repair must make both original service
instances available on one coherent search timeline and pass this mixed-day
transfer while retaining the same-day and negative controls. It must also
preserve the original twelve-case expectations and independently verify Python
itinerary serialization. Overlapping services, cross-midnight sampling, calendar
exceptions, the full source time range and date/DST boundaries remain broader
acceptance work. This baseline does not authorize a Melbourne travel-time claim.
