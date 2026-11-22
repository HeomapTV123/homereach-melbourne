# GTFS timetable audit

## Purpose and current checkpoint

[`scripts/audit_routing_timetable.py`](../scripts/audit_routing_timetable.py) reads every stop-time record in the three selected feeds of the pinned local GTFS archive. It checks source identity, references, numeric stop sequences and supported timetable semantics before any Melbourne routing experiment. It complements the existing input preflight, which checks small tables and stop-time headers.

At the `d5bc9a5` implementation checkpoint, the focused regression checks passed: **119 tests in 2.21 seconds**. The full project suite then passed: **1,093 tests in 27.95 seconds, with no skips**, using the pandas compatibility environment and third-party pytest plugin autoload disabled. These checks include controlled fixtures for malformed inputs and cleanup after failures.

**The supplied Windows audit passed.** On 22 November 2026 the maintainer supplied the [complete JSON report](evidence/routing_timetable_windows_2026-11-22.json), following a terminal transcript that associates the run with Windows, the `homereach` environment, checkout `d5bc9a5` and exit code 0. The report records completed source scans and logical trip checks for all three feeds, no issues/errors/blockers, matching aggregate counts, unchanged protected inputs and successful temporary cleanup.

The [checkpoint record](evidence/routing_timetable_windows_checkpoint_2026-11-22.json) preserves provenance and independently derived reconciliations. The raw report is retained byte for byte: **5,188 bytes**, SHA-256 `eea15e02ba4b255939a4be7c20954323d43436e629bd53218a4f60bf13a2ab49`. The receipt date is not an execution timestamp. The JSON contains no execution timestamp, source revision, runtime versions, duration or peak-memory measurement; the platform, environment and checkout association comes from the preceding terminal transcript. This review did not rerun the local archive.

A passed audit establishes only the checks described here. It does not certify the whole GTFS specification, load an engine network, validate transfers or station access, or establish travel times. Every audit report keeps `routing_ready` false and `journeys_computed` zero.

## Pinned source and verified coverage

The audit uses [`config/routing_pilot.json`](../config/routing_pilot.json) and [`config/gtfs_snapshot.json`](../config/gtfs_snapshot.json), with service date **2026-10-13** in **Australia/Melbourne**. The archive is `data/raw/transport/gtfs.zip`, with SHA-256:

```text
c88af3abcaf0872e45196dcc1d5af9bc20a82c54a00a9dfef46c809ec2e34814
```

The recorded source and active-row totals match the existing snapshot requirements:

| Nested feed | Scope recorded in the snapshot | Source rows | Active-date rows |
| --- | --- | ---: | ---: |
| 2 | Metropolitan train operational feed | 688,380 | 49,389 |
| 3 | Metropolitan tram | 2,568,892 | 232,760 |
| 4 | Myki bus, including regional town services | 8,589,911 | 1,029,597 |
| **Total** | **All three selected feeds** | **11,847,183** | **1,311,746** |

Activity is determined from calendar rules and calendar exceptions. All **311,483 declared trips** have stop-time records, including all **35,580 active trips**. The number of distinct indexed sequence rows and ordered rows checked both equals the complete source-row count. Active-trip, labelled-replacement, location and platform counts passed their snapshot checks. The report records 52 labelled replacement trips in feed 2.

All source rows are inspected, including inactive trips, events outside the morning window and stops outside the comparison LGAs. No geographic or morning-window filter runs before the timetable checks. The archive's complete outer-member inventory is checked, while timetable validation is limited to feeds 2, 3 and 4.

### Extended service-day times

| Feed | Source rows with times at/after 24:00:00 | Active-date rows with times at/after 24:00:00 | Maximum time across all source rows |
| --- | ---: | ---: | --- |
| 2 | 30,652 | 1,064 | 27:49:00 |
| 3 | 106,899 | 4,897 | 28:32:00 |
| 4 | 113,381 | 2,469 | 32:47:00 |
| **Total** | **250,932** | **8,430** | **32:47:00 overall** |

These counts describe stop-time rows, not distinct overnight trips or available journeys. The maxima include inactive trips. The report does not separately give active-trip time extrema, so it does not establish that an active trip reaches `32:47:00`. No unresolved-time, arrangement-required, flexible-service or effective continuous-service rows were recorded within the audit's supported scope.

The separate [service-day compatibility experiment](commute_routing_service_day_check.md) now tests those boundaries with a fictional timetable and independent date/time expectations. Its Linux run completes all twelve BUS queries: ordinary daytime, same-day exception and midnight-crossing cases pass, but four expected previous-service-day trips are missing. The command correctly fails that new gate. The Windows source audit remains a completed source-validation checkpoint; it does not change the frozen timetable or establish engine compatibility.

### Configuration fingerprint and Windows line endings

The report's pilot-configuration hash differs from the earlier Linux inventory because of line endings. The exact `routing_pilot.json` at `d5bc9a5` has 417 bytes with LF line endings and SHA-256 `0858fd0a8a36c7fad5f592bf243cc8e160b5c04dbf4df107c33ea8d1f6a4a473`. Replacing only its 13 LF endings with CRLF yields 430 bytes and SHA-256 `e6b23abed998e1fd17dcf8505056f07f4bdf17a13ad2ec5945592800ad051595`, exactly the uploaded report's value. This explains the fingerprint without a semantic configuration change. The snapshot hash matches the file at that revision, and the report records unchanged protected inputs during the run.

## How the audit works

The reader verifies the pinned archive fingerprint, rejects ambiguous ZIP members and CSV headers, and reads the required small tables as strings. It checks identifiers, references, service calendars, agency relationships and stop location types within the declared scope.

Stop-time rows stream into a disposable SQLite index in batches. The index orders records by trip and numeric `stop_sequence`; the audit therefore accepts interleaved trips and shuffled CSV rows. Sequence gaps and repeated visits to a stop are allowed. Duplicate trip/sequence keys, including numerically equivalent forms such as `01` and `1`, are errors.

The database primary key supplies the ordered traversal, so millions of records need not remain in Python memory. The implementation limits its row batch and SQLite cache, retains at most five examples per issue code, and reports complete issue counts. It processes one nested feed at a time.

Both the nested ZIP spool and SQLite index live under a private temporary directory inside the supplied `--work-root`. That root must already exist and resolve outside the project. The audit closes its handles and removes its owned temporary files on normal completion and handled failures; it does not remove other files in the work root. Cleanup success is reported explicitly.

Fingerprints of the protected pilot configuration, snapshot configuration and opened GTFS archive are rechecked after the audit, including handled failures. A detected change invalidates the result. If an I/O error prevents the recheck, the result is an operational error and `protected_inputs_unchanged` remains `null`; unreadable content is not reported as proven unchanged. This is before/after integrity checking, not a filesystem lock.

## Supported timetable semantics

Times are parsed as seconds within the GTFS service day. Values beyond `24:00:00` are retained, so an overnight service can continue into the next calendar day. The audit neither wraps a backwards clock time into tomorrow nor interpolates missing values. Populated approximate times are checked as supplied. See the [official GTFS Schedule reference](https://gtfs.org/documentation/schedule/reference/#stop_timestxt).

The fixed-stop timing contract follows the [MobilityData canonical validator's paired-time checks](https://github.com/MobilityData/gtfs-validator/blob/58294db0eb11a2e7f64008c16bfbe921bff3fc3b/main/src/main/java/org/mobilitydata/gtfsvalidator/validator/StopTimeArrivalAndDepartureTimeValidator.java), [endpoint checks](https://github.com/MobilityData/gtfs-validator/blob/58294db0eb11a2e7f64008c16bfbe921bff3fc3b/main/src/main/java/org/mobilitydata/gtfsvalidator/validator/MissingTripEdgeValidator.java), and [explicit timepoint handling](https://github.com/MobilityData/gtfs-validator/blob/58294db0eb11a2e7f64008c16bfbe921bff3fc3b/main/src/main/java/org/mobilitydata/gtfsvalidator/validator/TimepointTimeValidator.java):

| Condition | Audit treatment |
| --- | --- |
| Only arrival or only departure supplied | Error. |
| Missing arrival or departure at the first/last logical stop | Error under the canonical endpoint contract, when the trip can be assessed. |
| Missing times with explicit `timepoint=1` | Error. |
| Both times blank at an interior stop with `timepoint=0`, blank timepoint or no timepoint column | Incomplete timing; blocked pending a reviewed interpolation policy. |
| Departure before arrival at the same stop | Error. |
| Known arrival before the previous known departure | Error, including across ordinary untimed interior rows. |
| Equal arrival and departure | Accepted as zero dwell. |

The current reference's departure-time condition does not repeat the first/last requirement as explicitly as its arrival-time condition. This audit deliberately adopts the canonical validator's paired endpoint rule. An omitted timepoint is not converted into an explicit `1` when checking missing times.

Fixed-stop references must identify boarding stops with location type `0` or blank. Pickup/drop-off arrangement values `2` and `3` are accepted and reported. Blank optional extension columns are allowed. Populated Flex/location/window/booking fields, effective continuous stopping, and a `frequencies.txt` table produce unsupported-scope blockers. These features can be legitimate GTFS; the audit does not claim to validate their full semantics. Continuous settings inherit from routes unless a stop-time value overrides them, including an explicit `1` disabling continuous stopping. See the official [continuous-stopping definitions](https://gtfs.org/documentation/schedule/reference/#routestxt) and [frequency-service definitions](https://gtfs.org/documentation/schedule/reference/#frequenciestxt).

Unsupported rows interrupt known chronology anchors. Trips with unsupported or unorderable records do not receive a complete endpoint claim. Values beyond the index's integer storage range are also reported as unsupported rather than silently truncated.

## Reproduce the Windows audit

The following commands document how to reproduce the completed checkpoint. Use Anaconda Prompt / CMD with the existing **`homereach`** environment. The audit uses installed Python, NumPy and pandas; it installs no packages, downloads no inputs and starts no JVM. The separate routing and Osmium environments are not needed for this command.

After pulling the updated feature branch, use the external temporary directory `D:\homereach-conda\tmp`. The following captures JSON outside the project while leaving progress visible on stderr. The JSON report is emitted at completion or a handled failure. Echo the exit code immediately after the command, before another command changes it:

```bat
cd /d "D:\My project\homereach_melbourne"
if not exist "D:\homereach-conda\tmp" mkdir "D:\homereach-conda\tmp"
set "HOMEREACH_TIMETABLE_REPORT=D:\homereach-conda\tmp\routing-timetable-%RANDOM%-%RANDOM%.json"
conda run --no-capture-output -n homereach python -B scripts/audit_routing_timetable.py --work-root "D:\homereach-conda\tmp" --json > "%HOMEREACH_TIMETABLE_REPORT%"
echo Exit code: %ERRORLEVEL%
echo Report path: "%HOMEREACH_TIMETABLE_REPORT%"
```

Retain that report for review; a second full scan is unnecessary just to obtain JSON. The report itself remains outside the temporary workspace that the audit removes. The archive and project datasets are read only, and the command reports `project_files_written: 0`.

## Interpret the result

| Status | Exit code | Meaning |
| --- | ---: | --- |
| `passed` | 0 | All selected source rows were scanned and the implemented checks passed. |
| `blocked` | 2 | A required input is missing, timing is incomplete, an active trip is unusable, or service semantics require a reviewed extension. |
| `invalid` | 1 | A checked source/contract requirement failed, including fingerprint, row-count, reference, sequence or timetable violations. |
| `error` | 1 | An operational or internal processing failure prevented a trustworthy result, including unreadable storage or failed cleanup. |
| `environment_error` | 1 | A required Python dependency was unavailable before the audit started. |

Read `status`, `scan_complete`, protected-input integrity and cleanup fields together. `scan_complete: true` means the selected source scans reached their end; it does not override findings or establish routing readiness. On a handled read or processing failure, the report may contain only previously completed feeds, with no aggregate totals for a complete run. Missing totals must not be interpreted as zero rows or success.

Each feed's `logical_trip_checks_complete` concerns indexed timing and ordering. It does not establish active-trip coverage or validity by itself: an active trip with no usable sequence is reported separately and blocks the result. The overall status and coverage counts remain necessary.

Remaining work includes engine compatibility, departure-sample coverage, interpolation, frequency/Flex interpretation, transfer rules, shapes, pathways, coordinates, walking networks, station access, accessibility and actual journeys. Passing this audit supplies evidence for that later work; it does not complete it.
