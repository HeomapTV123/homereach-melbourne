# Service-day selection: source review and next experiment

## Decision at this checkpoint

The supplied Windows summary at `3dab578` reproduces the Linux service-day case
pattern: eight cases pass and four previous-service positive cases fail. The
[Windows evidence record](evidence/routing_service_day_windows_checkpoint_2026-11-23.json)
preserves the printed observations. The complete saved Windows JSON remains
unreviewed; its per-case problem details, additional global findings, runtime
identity and fingerprints cannot be inferred from the short summary.

Source inspection of the pinned integration identifies a mechanism consistent
with the retained Linux results: the request selects active services for one
calendar date, while timetable times retain their service-day seconds. A
following-calendar-day request therefore excludes a preceding-date-only service
before the search can use its extended-hour departures.

Keep the existing twelve-case diagnostic and its failed baseline. The next
engineering experiment should test that date selection directly with paired
native requests. That probe is specified below; it has **not been implemented or
run at this checkpoint**. No replacement engine, timetable transformation,
installed-package patch or production routing correction is introduced here.

## Reviewed sources

| Component | Pinned source | Relevant behaviour |
|---|---|---|
| Python request construction | r5py **1.1.7**, [`RegionalTask.departure`](https://github.com/r5py/r5py/blob/v1.1.7/src/r5py/r5/regional_task.py) | Assigns the native request date from the supplied civil date and the start offset from its hour/minute. |
| Native service selection | R5 **v7.5.1-r5py**, [`McRaptorSuboptimalPathProfileRouter`](https://github.com/r5py/r5/blob/v7.5.1-r5py/src/main/java/com/conveyal/r5/profile/McRaptorSuboptimalPathProfileRouter.java) | Its constructor obtains the active-service set for the request date. The search excludes nonintersecting patterns and schedules whose service code is inactive. |
| Imported times and calendars | R5 **v7.5.1-r5py**, [`TransitLayer`](https://github.com/r5py/r5/blob/v7.5.1-r5py/src/main/java/com/conveyal/r5/transit/TransitLayer.java) | Copies imported arrival/departure seconds into timetable arrays. Its date lookup evaluates each service on the single supplied date. |
| Python itinerary timestamps | r5py **1.1.7**, [`TripPlanner.transit_paths`](https://github.com/r5py/r5py/blob/v1.1.7/src/r5py/r5/trip_planner.py) | Builds returned datetimes by combining the Python request's midnight with native state/sample seconds. |

The Python files were inspected directly in the reviewed r5py 1.1.7 wheel. Wheel
SHA-256: `d28390cb4ad3d640dbea208e7c78c9cd5420ba112aecc12a725a2239468d424d`.
The corresponding file hashes are:

| Wheel member | SHA-256 |
|---|---|
| `r5py/r5/regional_task.py` | `2cb5729eb461fc66d7e482f833373121e87e8b21cc68f81f46cc4d5ea8be6876` |
| `r5py/r5/trip_planner.py` | `541bcf3ec644bb717195518699ad540d1c448330539e26b1f36cd850ff7674a7` |

These are source-review fingerprints, not fresh measurements of the maintainer's
installed Windows files. The official [advanced-use guide](https://r5py.readthedocs.io/stable/user-guide/user-manual/advanced-use.html#route-with-gtfs-data-sets-that-have-trips-after-24-00-00)
and [upstream report #508](https://github.com/r5py/r5py/issues/508) describe related
extended-time limitations. That issue used a different r5py version and API;
this project's retained experiment supplies the specific evidence for its
selected integration.

## How the observed cases follow from that mechanism

For the fixed fictional case, Tuesday `25:05:00` and Wednesday 01:05 refer to the
same local event. The ordinary Wednesday request nevertheless activates
Wednesday's service set. Its Tuesday-only service is excluded; the raw `25:05`
value is not automatically brought into the Wednesday search as 01:05.

The midnight-crossing control begins on Tuesday, so Tuesday's service is active.
Its 23:58 departure and 24:03 arrival remain eligible. Adding the arrival seconds
to Tuesday midnight produces Wednesday 00:03. This explains why that control
can pass while a later Wednesday query misses preceding-service-day trips.

The same-day calendar controls are useful here: the added Tuesday service is
found on Tuesday, while the removed one is absent. The previous-day removal's
empty result alone would not establish correct exception handling, because a
search excluding every preceding-day service would also return empty.

The Linux report establishes missing results without query exceptions. The
Windows summary establishes matching displayed outcomes and counts; the full
Windows report is still required to check the detailed reasons and metadata.

## Next controlled native experiment

Use the unchanged fictional network and reviewed JAR, with the existing scoped
walking corrections, six-minute sampling window and resource limits. Start with
the fixed Wednesday 01:00 case and compare two cloned requests:

| Arm | Native service date | Native sampling window | Local interval represented in this fixture |
|---|---|---|---|
| Baseline | Wednesday 2026-10-14 | 01:00–01:06 | Wednesday 01:00–01:06 |
| Previous-day anchor | Tuesday 2026-10-13 | 25:00–25:06 | Wednesday 01:00–01:06 |

This is a diagnostic representation of the same interval on these fixed dates;
it is not a general DST policy. Capture the native request fields, active service
codes, timetable identities, access/egress cost maps, sampled offsets and returned
state chains immediately after native routing. The paired requests should have
the same normalized civil sample times and unchanged costs. The native sampler
is seeded from origin latitude, which remains fixed, but the probe must verify
the actual sample correspondence rather than assume it.

Do not serialize the counterfactual through the normal Python itinerary method.
Changing only the Java date and integer offsets leaves the Python midnight base
unchanged and can label returned events a day late. Inspect raw native states
first, retain their service-date association, and compare those fields with the
independent fixture timetable. A diagnostic civil-time derivation must stay
separate from any claimed engine-returned itinerary.

If the expected native trip is recovered, that would isolate the role of the
selected service date. Include ordinary-current-day and removed/inactive
controls so the experiment also exposes what the prior-date view excludes.
Preserve the unmodified baseline and report unchanged original inputs, restored
temporary scopes and cleanup. A missing trip, exception, changed cost map or
mismatched sampled interval must remain a failed or inconclusive probe.

## Why this is not yet a general repair

A real journey can use a preceding day's late service and then transfer to a
current day's early service. Simply running each date separately and joining
completed answers does not search a transfer between those views. Similarly,
setting every request to yesterday would remove valid current-day services.

A general solution must represent the relevant service instances on a coherent
time axis, preserve their individual calendar exceptions and trip identities,
and support transfers between them. It also needs tests for overlapping services,
midnight-spanning query windows, date boundaries, DST and the complete range of
source times. Selecting or implementing that integration is a later decision.
The original GTFS archive and the completed source audit remain the reference.

## Immediate evidence handoff

Provide the JSON already saved by the Windows run:

```text
D:\homereach-conda\tmp\routing-service-day-22692-22001.json
```

There is no need to rerun the engine to supply it. Review its runtime identity,
source/fixture hashes, per-case reasons, complete global findings and raw returned
rows before declaring complete cross-platform report equivalence. This
documentation checkpoint adds no code and does not clear the compatibility gate.
