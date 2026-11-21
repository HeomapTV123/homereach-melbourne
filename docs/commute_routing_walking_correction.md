# Experimental correction for the synthetic walking paths

## Checkpoint and scope

The explicit `--correct-walking-paths` mode passes the reviewed synthetic fixture's timing, walking geometry, distance and duration checks on Linux and in the maintainer's supplied Windows run. It requires both `--isolate-itinerary-legs` and `--check-walking-geometry`; the existing modes retain their previous behavior. This is a bounded experiment against r5py 1.1.7 and the SHA-256-verified R5 `v7.5.1-r5py` JAR, not a production routing integration.

The maintainer's earlier Windows run at `1be659f` confirmed the geometry baseline failure: the timing checks passed, but all 121 walking geometries failed the endpoint, path and geometry-versus-distance checks. That [failed Windows checkpoint](evidence/routing_geometry_windows_checkpoint_2026-11-18.json) is preserved. The later [corrected Windows checkpoint at `219f326`](evidence/routing_walk_correction_windows_checkpoint_2026-11-21.json), supplied on 21 November 2026, records **`PASSED` with exit code 0**: 53 transit alternatives, 107 walking legs, zero enabled failures, 159 leg snapshots, restoration of all correction scopes and successful temporary cleanup. Both Windows checkpoints are supplied console evidence; no complete Windows raw-leg JSON report or execution timestamp was supplied.

The [corrected Linux report](evidence/routing_walk_correction_linux_2026-11-18.json) preserves every returned itinerary row and geometry. Its three queries use the same fictional streets, timetable, coordinates and routing parameters as the [earlier geometry experiment](commute_routing_geometry_check.md). The [saved baseline/correction comparison](evidence/routing_walk_correction_comparison_2026-11-18.json) records the counts below, the walking coordinates and the changed set of observed bus departures.

| Observation | Geometry baseline, with leg isolation | Walking correction enabled, Linux |
| --- | ---: | ---: |
| Transit alternatives observed | 60 | 53 |
| Transit leg rows | 180 | 159 |
| Walking legs checked, including the direct query | 121 | 107 |
| Chronology overlaps / bus-wait mismatches | 0 / 0 | 0 / 0 |
| Walking endpoint / off-reference-path failures | 121 / 121 | 0 / 0 |
| Geometry-versus-reported-distance failures | 121 | 0 |
| Reported-versus-reference-distance failures | 61 | 0 |
| Independent walking-duration failures | Not separately checked | 0 |

The corrected run also has zero malformed options, unexpected leg sequences, egress-padding mismatches, malformed geometries, incomplete options and unsupported coordinate reference systems. The supplied Windows console reports the same timing, geometry, duration and snapshot counts, and the same displayed direct/access/egress distances. This agreement does not establish exact equality of every returned row or coordinate. Both runs report successful restoration and temporary cleanup, no real project datasets read and no Melbourne journeys computed.

## Three separate corrections

### 1. Rebuild the fixed fixture's derived street index

The pinned [R5 `IntHashGrid.insert(LineString)` implementation](https://github.com/r5py/r5/blob/v7.5.1-r5py/src/main/java/com/conveyal/r5/streets/IntHashGrid.java) subtracts the next coordinate from the current one, then adds that difference to the current coordinate during interpolation. In the observed case, this indexes reflected segment positions. The nearest-edge search therefore omits an edge that actually contains the requested destination.

The native comparison makes this visible before itinerary assembly. For destination longitude `0.0299`, the original index selects an eastern edge starting at `0.0300`, with an approximately 11.1-metre perpendicular connector. The containing western edge is absent from that candidate query. The original direct result reports 2656.089 metres. After rebuilding the index, the containing edge is selected, the destination's off-edge distance is zero, and the native direct result is 2644.836 metres. These observations and the native split values are retained in the [paired index evidence](evidence/routing_direct_index_correction_linux_2026-11-18.json).

[`routing_street_index_correction.py`](../scripts/routing_street_index_correction.py) inserts each reviewed street edge's native fixed-coordinate envelope through the existing `IntHashGrid.insert(Envelope, edgeID)` overload. It checks five sample points on each of the fixture's 84 street pairs: the original index omits 322 of 420 required edge candidates; the rebuilt index omits none. This replaces only the derived spatial index during the experiment.

Before replacing it, the adapter verifies the exact generated XML fingerprint, all 49 grid vertices, two additional transit-stop vertices, the 84 street pairs and two zero-length stop-connector pairs. It checks the edge geometries, permissions and links against the fixed fixture, and verifies that both existing native stop links already match the GTFS stop coordinates. A graph fingerprint before and after the scope establishes that the underlying graph is unchanged. The original index is restored on exit.

That stop-link check is essential: the network is built before this correction is applied. Rebuilding an index at this point would not repair arbitrary incorrect stop links created during network construction. This adapter consequently refuses any graph that differs from the reviewed fixture; it is not a general index or stop-link repair for Melbourne inputs.

### 2. Keep reverse origin states associated with their real endpoints

The earlier [native state evidence](evidence/routing_reverse_origin_state_linux_2026-11-18.json) establishes a distinct error in [R5 `StreetRouter.setOrigin`](https://github.com/r5py/r5/blob/v7.5.1-r5py/src/main/java/com/conveyal/r5/streets/StreetRouter.java): the reverse-search initialization swaps vertex fields without moving the associated directional edge, distance and duration together. In the baseline fixture this produces a final walking leg of 677.897 metres and 678 seconds for an independently established path of about 11.119 metres.

[`routing_street_origin_correction.py`](../scripts/routing_street_origin_correction.py) wraps the `StreetRouter` factory used by the pinned Python `TripPlanner`. The original native method first establishes its split and internal metadata. For a reverse WALK search, the reviewed [Java helper](../scripts/routing_native/HomeReachStreetOrigins.java) then creates fresh initial states with each endpoint's correct directional back-edge, partial-edge distance and duration, including the origin's off-street connector where present. It checks the initial queue and state-map shape before replacing those two collections. It does not mutate the costs of objects already sitting in a priority queue.

Forward initial states remain native. The proxy permits one origin and one search per fresh WALK router and rejects reverse point-to-point searches. It also retains the router context associated with returned terminal states so the geometry component can read the same native split and state chain.

This override is local to the Python planner namespace. **Other callers inside R5 do not receive a globally patched Java `StreetRouter`.** The experiment does not establish that transfers, native internal searches, other transport modes or a general routing engine have been corrected.

The separate [native origin regression evidence](evidence/routing_native_origin_regressions_linux_2026-11-18.json) covers 16 cases: four origin positions, two walking speeds, and both search directions. It checks endpoint and directional-edge associations, distances, durations, queue ordering, state-map identities and fresh replacement of reverse states. The pinned WALK speed comes from the request; these cases do not establish handling of mode-specific or direction-specific costs for other modes.

### 3. Construct geometry from the selected native partial edges

The pinned [r5py `StreetSegment` implementation](https://github.com/r5py/r5py/blob/v1.1.7/src/r5py/r5/street_segment.py) joins complete edge geometries. That can draw an entire street edge even when the route starts or ends partway along it. Correcting native costs alone therefore does not repair the returned line.

[`routing_street_geometry_correction.py`](../scripts/routing_street_geometry_correction.py) constructs the walking segment before itinerary leg assembly. It reads the actual native origin/destination splits and selected state chain, clips the first and last edges at those splits, retains intermediate edge vertices and genuine detours, and handles zero-length stop connectors. For a reverse search, it returns the coordinates in traveller order. Edge endpoints and state directions must agree; unsupported or contradictory state chains are refused.

The geometry constructor does not use the independent reference path to choose coordinates, and it preserves the native terminal state's distance and duration. The serializer subsequently records all returned rows without clipping, snapping, reversing or filtering them.

The runtime adapter rejects a direct coordinate destination with nonzero off-street distance. The pinned `StreetRouter.getState(Split)` leaves that perpendicular destination connector out of its cost; drawing such a connector while retaining the incomplete cost would hide another error. The corrected fixture's destination lies on its selected native edge, so this unsupported case is not needed for the passing experiment.

## Validation remains independent

The original leg-isolation adapter remains enabled. It gives each itinerary its own copy of cached leg state and protects chronology while the walking corrections address separate native-search and geometry errors. The existing timetable, bus-stop, route, five-minute ride, inactive-service, chronology, wait and complete `WALK → BUS → WALK` assertions remain in force, including the pinned implementation's 60-second egress padding.

The [independent geometry oracle](../scripts/routing_walk_geometry.py) is unchanged. It derives reference paths from the committed street XML and fixed GTFS stop coordinates, rather than from corrected native output. Its endpoint/path tolerance remains 2 metres; its length tolerance remains the greater of 2 metres and 0.2% of reference length. It checks both the drawn line against the reported distance and the reported distance against the independently proved path.

The corrected mode additionally validates every walking duration against reference distance divided by the fixed walking speed of 3.6 km/h (1 metre per second). The duration allowance is the existing reference-length allowance divided by that same speed. This uses independent expected path lengths and keeps the same numerical precision allowance; it does not derive expected durations from an engine-reported distance.

| Walking role | Independent reference | Corrected native distance | Corrected duration | Duration allowance |
| --- | ---: | ---: | ---: | ---: |
| Direct | 2646.439 m | 2644.836 m | 2645 s | About 5.293 s |
| Access | 11.119 m | 11.100 m | 12 s | 2 s |
| Egress | 11.119 m | 11.254 m | 12 s | 2 s |

The number of alternatives is an observation, not a required count. The original run contains 23 BUS legs departing at 08:05, 30 at 08:10 and seven at 08:15. The corrected run retains the first two groups and returns no 08:15 group. The project adds no output filter, and all 53 returned alternatives are preserved.

The subsequent [departure-sampling investigation](commute_routing_departure_sampling.md) establishes the mechanism for this fixture. A target-arrival cutoff is retained across sampled departures. The corrected earliest arrival of 08:10:12, plus a five-minute allowance, prunes the seven later samples that require the 08:15 BUS arriving at 08:20. A separate diagnostic resets only that cutoff for each sample and returns 60 alternatives with the same sampled keys, request and access/egress maps; the original 53 native chains and complete itinerary rows remain unchanged. This probe does not change the shipped smoke runner or claim a general engine repair. The passing smoke test validates the returned legs; complete route enumeration and a production-capable routing integration remain unvalidated.

## Runtime guards and temporary helper

The combined mode runs only inside the fresh synthetic worker, with one Python routing job and a 1 GiB Java heap limit. Source guards require the reviewed r5py 1.1.7 implementation, expected loaded method/module identities, the fixed R5 JAR fingerprint and the reviewed Java helper source. Python source fingerprints normalize CRLF to LF for Windows. Different sources, already modified methods and nested correction scopes are refused rather than silently falling back to uncorrected behavior.

The origin helper is compiled by the **already running Java 21 compiler**, obtained through `javax.tools.ToolProvider`. Its source and generated class files are placed in the run's temporary workspace. A dedicated `URLClassLoader` loads that class with a checked source location; the report records the compiler version and emitted class fingerprint. A Java runtime without the compiler module is refused. No external build service or package download is used.

The context managers restore the original spatial index, planner namespace and geometry method on normal completion or exceptions. The original leg-addition method is also restored; the temporary helper loader is closed. The parent validator requires application, actual use and restoration audit records for all requested components before accepting a pass. It also requires unchanged graph fingerprints, valid stop-link verification, complete rebuilt-index candidate coverage and preservation of native costs by geometry construction.

The installed Python package, original JAR, committed fixture and real project datasets remain unchanged. These guards constrain compatibility and the experiment's inputs; they are not a Java/native filesystem or network sandbox.

## Verification of this checkpoint

The final local regression run passed **974 tests in 54.95 seconds**. Ordinary tests cover the existing project behavior as well as the new source/runtime guards, native-state proxy behavior, partial-edge geometry construction, fixed-fixture index checks, restoration and parent validation. These tests do not launch the native engine; the separate native experiments supply that evidence.

The final combined Linux native run completed in **13.383 seconds**, reported `PASSED` and exited with code 0. It used r5py 1.1.7, Java 21.0.13, the same pinned R5 JAR and unchanged fixture hashes. The saved report contains all three query results, all 159 transit rows, the direct walking row, and all 107 walking observations. The inactive-service query returned no itinerary. All enabled timing, sequence, geometry and duration checks passed.

The same report confirms 159 independent leg snapshots, successful restoration of all four scoped changes, closure of the temporary helper loader, unchanged graph fingerprints and temporary-workspace removal. Its execution metadata records canonical-LF hashes of the runner, worker, fixture generator, independent oracle, adapters and Java helper source. The comparison confirms identical engine/input fingerprints and an unchanged independent geometry oracle. That historical 18 November report records the 60-to-53 change as unresolved at capture; the later [departure-sampling investigation](commute_routing_departure_sampling.md) explains its mechanism without rewriting that evidence or treating the two alternative sets as equivalent.

The [16-case native origin regression report](evidence/routing_native_origin_regressions_linux_2026-11-18.json) and [paired native index probe](evidence/routing_direct_index_correction_linux_2026-11-18.json) provide additional evidence for the two native-search corrections. The subsequent [supplied Windows run](evidence/routing_walk_correction_windows_checkpoint_2026-11-21.json) separately verifies the combined fixture command on that runtime; it does not reproduce those additional native probes or supply their internal state traces.

## Verified Windows command

The maintainer completed this command successfully at `219f326` using the existing D: environment, reviewed JAR and temporary directory. The command is retained for reproduction in Anaconda Prompt / CMD; another run is not required merely to establish the supplied checkpoint.

```bat
cd /d "D:\My project\homereach_melbourne"
git switch feat/commute-location-review
git pull --ff-only origin feat/commute-location-review
conda run --no-capture-output --prefix "D:\homereach-conda\envs\homereach-routing" python -B scripts/run_routing_smoke_test.py --jar "D:\homereach-conda\r5-engine\r5-v7.5.1-r5py-all.jar" --work-root "D:\homereach-conda\tmp" --isolate-itinerary-legs --check-walking-geometry --correct-walking-paths
echo Exit code: %ERRORLEVEL%
```

The supplied Windows result is `PASSED`, exit code 0, zero enabled timing/geometry/duration failures, verified correction restoration and successful workspace cleanup. Both platforms returned 53 alternatives in these observations; that count remains an observation rather than a pass criterion. Exact raw-leg equivalence between the platforms has not been established from console output.

For a future run that needs a complete report, use the following instead of the preceding smoke-test command. It creates a new report outside the checkout:

```bat
set "HOMEREACH_WALK_REPORT=D:\homereach-conda\tmp\routing-walk-correction-%RANDOM%-%RANDOM%.json"
conda run --no-capture-output --prefix "D:\homereach-conda\envs\homereach-routing" python -B scripts/run_routing_smoke_test.py --jar "D:\homereach-conda\r5-engine\r5-v7.5.1-r5py-all.jar" --work-root "D:\homereach-conda\tmp" --isolate-itinerary-legs --check-walking-geometry --correct-walking-paths --json > "%HOMEREACH_WALK_REPORT%"
echo Exit code: %ERRORLEVEL%
type "%HOMEREACH_WALK_REPORT%"
```

If the run refuses a source/compiler check or fails an itinerary assertion, retain that report. Omitting `--correct-walking-paths` reproduces the geometry baseline; omitting the geometry flag as well retains the historical timing-only checkpoint. The stronger corrected mode cannot be selected without both companion flags.

## Remaining project work

This checkpoint establishes a controlled synthetic experiment with independently checked costs and drawn walking paths. It does not authorize using the correction on arbitrary networks. Before a Melbourne development itinerary, the project still needs complete GTFS stop-time and reference validation, reviewed street/GTFS loading, route and transfer checks, and examination of station access and walking connectivity. Public access, barriers, vertical movement, accessibility and actual Melbourne journey timing remain unvalidated.
