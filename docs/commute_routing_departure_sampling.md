# Why the corrected fixture returns 53 transit alternatives

## Finding and scope

The corrected synthetic smoke test passes its enabled returned-itinerary checks on Linux and in the [supplied Windows run at `219f326`](evidence/routing_walk_correction_windows_checkpoint_2026-11-21.json). Both observations report 53 transit alternatives and 107 checked walking legs. The Windows checkpoint is complete; repeating that command is not required to record its pass.

A separate paired native experiment on Linux now explains the change from the earlier 60 alternatives. The pinned native router retains a target-arrival pruning bound across its sampled departures. After the walking correction reduces the final walking cost, that retained bound excludes seven later samples that need the 08:15 bus. Clearing only that bound for each sample in a diagnostic counterfactual restores the seven alternatives. The original 53 native chains and complete serialized itineraries remain unchanged after aligning by sampled departure and ignoring option numbering.

This update records evidence and documentation. It does not change the smoke runner, its pass criteria, the fixed fixture, the independent reference oracle, installed packages or the R5 JAR. The experimental reset is not enabled by `--correct-walking-paths` and is not a general routing fix. The remaining question is the departure-coverage contract needed for future commute results, rather than an unexplained count change in this fixture.

## Paired result

The [full native report](evidence/routing_departure_sampling_2026-11-21/paired_count_result.json) records two active BUS queries in the same temporary fixture network. Both use the existing leg, index, origin and geometry corrections. The observation arm leaves the target bound unchanged. The counterfactual arm clears only `bestTimesAtTargetByAccessMode` at the start of each sampled search, using the diagnostic hook described below.

| Observation | Existing corrected integration | Diagnostic reset per sample |
| --- | ---: | ---: |
| Native sampled departure keys | 60 | 60 |
| Samples with a returned native chain | 53 | 60 |
| Empty native sample collections | 7 | 0 |
| Serialized itinerary leg rows | 159 | 180 |
| Alternatives boarding the 08:05 bus | 23 | 23 |
| Alternatives boarding the 08:10 bus | 30 | 30 |
| Alternatives boarding the 08:15 bus | 0 | 7 |
| Original 53 native chains and full itineraries retained | Reference | All unchanged |

These counts describe alternatives for sampled origin departure times. They do not represent 60 different bus services or establish exhaustive enumeration of all feasible itineraries.

The [comparison and 22 checks](evidence/routing_departure_sampling_2026-11-21/paired_count_comparison.json) establish identical recorded requests, access/egress cost maps, access-map iteration, all 60 sample keys and their callback order. The observation arm's serialized transit rows also match the [earlier corrected Linux checkpoint](evidence/routing_walk_correction_linux_2026-11-18.json), after ignoring option numbering. Native final states were captured immediately after native `route()` returned, before Python itinerary assembly, and verified unchanged after assembly. Thus the seven empty samples already exist in the native result; Python serialization does not remove them.

## Source mechanism and observed cutoff

The pinned [R5 router source](https://github.com/r5py/r5/blob/v7.5.1-r5py/src/main/java/com/conveyal/r5/profile/McRaptorSuboptimalPathProfileRouter.java) generates ascending departure samples. It clears several sample-specific state collections between iterations, while retaining `bestTimesAtTargetByAccessMode`. With `maxFare=-1`, its `addState` method rejects a candidate state when:

```text
candidate_state_time - suboptimalMinutes * 60 > retained_target_bound
```

This comparison uses the candidate state's absolute time and a previously found target-arrival bound. It is not a comparison of each candidate's complete final itinerary. The recorded request retains the five-minute allowance defined in the pinned [ProfileRequest](https://github.com/r5py/r5/blob/v7.5.1-r5py/src/main/java/com/conveyal/r5/profile/ProfileRequest.java); the experiment does not increase that allowance or replace the normal [dominance rule](https://github.com/r5py/r5/blob/v7.5.1-r5py/src/main/java/com/conveyal/r5/profile/SuboptimalDominatingList.java).

The corrected first successful sample reaches the native target at **08:10:12**: the first bus arrives at 08:10 and the corrected final walk takes 12 seconds. The observation trace retains that bound for every later sample. Adding the unchanged five-minute allowance yields a latest accepted native state time of **08:15:12**. The third bus arrives at its destination stop at **08:20:00**, so its arrival state is rejected:

```text
30000 - 300 > 29412
08:20:00 minus five minutes > 08:10:12
```

The original geometry baseline reported a much larger final walking cost of 678 seconds. Its first target time would therefore permit later arrivals under the same five-minute allowance. The paired experiment holds the corrected walking costs fixed and changes only the retained cutoff, establishing why the seven alternatives disappear with those corrected costs. It does not justify restoring an incorrect walking cost to obtain a desired result count.

The seven affected sampled origin departures are:

| Origin departure | Arrival at the boarding stop after 12 seconds |
| --- | --- |
| 08:08:52 | 08:09:04 |
| 08:09:04 | 08:09:16 |
| 08:09:13 | 08:09:25 |
| 08:09:23 | 08:09:35 |
| 08:09:35 | 08:09:47 |
| 08:09:43 | 08:09:55 |
| 08:09:49 | 08:10:01 |

With the unchanged native 60-second boarding allowance, these samples cannot board the 08:10 bus but can board the 08:15 service. All seven recovered native chains board at 08:15, alight at 08:20 after a five-minute ride, and reach the native target at 08:20:12. Their BUS rows match the earlier baseline for the same origin samples. The Python itinerary representation retains its previously documented separate 60-second egress padding, so its final WALK departs at 08:21; native target times and displayed itinerary times must not be conflated.

## Why the diagnostic hook is bounded

The probe temporarily wraps the native router's state-list callback in the Python planner namespace. In the counterfactual arm, it clears the private target-bound map at the first callback for each sampled departure and then calls the original callback with the same argument. The request, sampled times, costs and timetable are unchanged. The probe does not manually edit native state chains or returned rows; the additional results are produced by the normal native search after the bound reset.

The callback occurs after `addState` has already checked duration and target-bound limits. Consequently it would be too late as a universal reset point if the first access state were pruned before reaching the callback. For this fixture, the probe records the actual native access iteration: the west stop with a 12-second access cost precedes the east stop with a 2657-second cost. It verifies for all 60 samples in each arm that the first access state passes those earlier checks, the callback occurs at round zero, and no state bags yet exist. The reset therefore precedes transit relaxation in this observed fixture.

Temporary Python namespace overrides and all four correction scopes are restored. The counterfactual query's cleared map is not restored to its previous contents; its router instance is discarded. The graph fingerprint, fixture inputs, JAR and eight execution-source fingerprints are unchanged after the pair, and the temporary workspace is removed. These observations are recorded in the report, rather than inferred from a successful process exit alone.

## Evidence and reproduction boundaries

The paired experiment ran on **21 November 2026, 15:00:20–15:00:27 UTC**, taking **6.912 seconds**. It used Python 3.12.14, Java 21.0.13, r5py 1.1.7, JPype1 1.7.1, GeoPandas 1.2.0, pandas 3.0.3, NumPy 2.3.5, Shapely 2.2.0, pyproj 3.8.0 and rasterio 1.5.2. Execution sources match commit `219f326196ceb0208104cf7eb5f88e24a4084d93`.

| Artifact | Purpose |
| --- | --- |
| [Full paired report](evidence/routing_departure_sampling_2026-11-21/paired_count_result.json) | Both native traces, every returned row and geometry, all sampled keys, requests, costs, runtime and restoration evidence |
| [Comparison report](evidence/routing_departure_sampling_2026-11-21/paired_count_comparison.json) | All 60 sample outcomes, the seven recovered chains and itineraries, 22 passing comparisons and retained-content hashes |
| [Executed probe source](evidence/routing_departure_sampling_2026-11-21/probe_count.py.txt) | Exact research script used to generate the native evidence |
| [Comparison source](evidence/routing_departure_sampling_2026-11-21/compare_count.py.txt) | Read-only derivation and assertions against the native report and historical checkpoints |

The raw report's SHA-256 is `f8eb58f79c5177d7ade8e5caa2bf99c90eb8389228e5020d2add2e269b294e76`. The executed probe's canonical-LF SHA-256 is `f0e1d8b117bcf770f42f1352f5776a7bc86c26c1031bdcbd226e0ea2a1874472`. The reviewed engine JAR remains `d50be106cadd7b636cfc0e209052767d7df570629f79fdf98ecd5cf5d2d89be7`.

The two Python sources are archived as text to preserve the exact executed research record. They contain the original scratch checkout and JAR/workspace paths; they are not portable project commands. To rerun only the comparison without R5, copy the archived raw JSON and both source files into a separate research directory, restore the original `.py` names, preserve `probe_count.py` byte-for-byte, and adapt only `compare_count.py`'s `ROOT` to the checkout. Its recorded-probe hash assertion then remains meaningful. A fresh native reproduction instead adapts the probe's checkout and JAR/workspace paths and regenerates the raw report with the new source fingerprint before comparing it. Such an edited run must be reported as a new experiment. No new command or environment change is required on the maintainer's Windows machine for this evidence update.

This Linux pair runs **two active BUS queries**. It is not another run of the three-query smoke suite and does not independently trace native Windows state. The supplied Windows counts agree with the existing corrected observation; its console output alone does not prove internal trace equality. No real project dataset was read and no Melbourne journey was computed.

## Acceptance decision and next milestone

Record the successful Windows smoke checkpoint and close the fixture-specific question about the 60-to-53 change. Preserve the existing timing, geometry and duration checks and all historical failure reports. A required count of 60 would be a poor substitute for checking whether each requested departure has an appropriate result or an explicit reason for its absence.

Before relying on commute estimates, define the intended result contract: which departure times are sampled, which alternatives can be removed by policy, and how empty samples affect any reported summary. A general integration must implement and validate that contract without depending on this fixture's callback position. The evidence here establishes a mechanism, not the universal correctness or incorrectness of profile-wide pruning, and it does not establish exhaustive routing.

The [complete GTFS timetable audit](commute_gtfs_timetable_audit.md) implements the next input milestone: a read-only scan of every selected stop-time row, trip/stop references, service applicability and timetable chronology, including times beyond `24:00:00`. The supplied Windows report passes all 11,847,183 source rows and 1,311,746 active rows, with no reported issues or input changes. Its 8,430 active extended-time rows motivate the separate [service-day engine experiment](commute_routing_service_day_check.md). The existing archive/small-table preflight remains a separate, narrower command. This source audit does not select a general engine correction. Melbourne network compatibility, transfers, provisional station access and walking connections still require their own checks before any real travel-time result is presented.
