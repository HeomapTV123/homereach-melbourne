# Combined service-day transfer: regression contract

## Decision and evidence boundary

This contract is now exercised by a separate
[three-stop native transfer baseline](commute_service_day_transfer_check.md).
The baseline preserves the original service dates and timetable seconds. It
does not implement a timetable transformation or service-day correction.

The [paired anchor probe](commute_service_day_anchor_probe.md) passes on Linux
and in the fully reviewed Windows report at `c8f8130`. All seven pairs, 840
samples, 190 native paths and 570 state snapshots match; source/input hashes and
validator replay agree. Runtime versions and execution metadata differ. The
original service-day compatibility baseline remains failed and `routing_ready`
remains `false`.

The discriminating test requires both service dates in one continuous journey.
Selecting yesterday recovers the extended-time trips but loses the current-day
control. Joining completed answers from separate single-date searches does not
construct a transfer between those searches.

## Minimal discriminating timetable

Create a distinct fictional fixture with stops A, B and C. Use the same fixed
non-DST dates and `Australia/Melbourne` timezone as the anchor experiment. Query
from A to C on Wednesday 2026-10-14 shortly before 01:05, with sufficient access
time for the first ride. Retain a bounded sampling window and all sample keys.

| Ride | Service instance | Original timetable | Independent expected civil interval |
|---|---|---|---|
| A to B | Tuesday 2026-10-13 | 25:05:00 to 25:10:00 | Wednesday 2026-10-14 01:05 to 01:10 |
| B to C | Wednesday 2026-10-14 | 01:15:00 to 01:20:00 | Wednesday 2026-10-14 01:15 to 01:20 |

The intended path has two five-minute rides and a five-minute scheduled gap at
B. This is not a claimed total door-to-door duration: access, transfer rules and
egress must be specified and checked separately. Preserve each trip's original
service date and timetable seconds alongside any explicitly derived civil time.
The [GTFS Schedule reference](https://gtfs.org/documentation/schedule/reference/#stop_timestxt)
defines times beyond 24:00:00 within a service day; the fixed-date example above
does not establish a general DST conversion policy.

## Required controls and assertions

| Case | Required assertion |
|---|---|
| Mixed-service-day positive | One native path contains A-to-B and B-to-C in order, with their different original service dates, correct trip/stop identities and expected civil clocks. |
| Same-day transfer control | The same physical two-ride layout and civil timetable succeeds with both rides attached to Wednesday. This isolates ordinary transfer support from service-day handling. |
| Mixed-day removal of first ride | A Tuesday calendar exception removes A-to-B; the required two-bus chain must be absent. |
| Mixed-day removal of second ride | A Wednesday calendar exception removes B-to-C; the required two-bus chain must be absent. |
| Mixed-day impossible connection | B-to-C departs before A-to-B arrives; the required chain must be absent. |
| Same-day removal of first ride | A Wednesday calendar exception removes A-to-B from the otherwise working transfer; the required chain must be absent. |
| Same-day removal of second ride | A Wednesday calendar exception removes B-to-C from the otherwise working transfer; the required chain must be absent. |
| Same-day impossible connection | Both Wednesday services are active, but B-to-C departs before A-to-B arrives; the required chain must be absent. |

The three same-day negative cases make the controls informative even while the
mixed-day positive fails. Each case has its own GTFS archive and fresh network,
so the same-day control cannot contribute an alternative trip to the mixed-day
case.

Declare expected calendars, original service-instance identities, timetable
values and civil timestamps independently of returned engine results and of the
fixture generator. Check each native state and the complete ordered chain.
Explicitly specify transfer walking/slack rules, and verify that the positive
case has enough time under them. A walking shortcut or one-bus result cannot
satisfy the required two-bus positive assertion. For negative cases, distinguish
absence of the required chain from absence of every possible journey.

Retain the actual sampled offsets, native paths and query errors. Report observed
path counts without requiring the earlier probe's count of 38 or claiming full
departure coverage. A positive must recover a feasible declared journey; empty
output cannot count as success. The same-day control must pass before attributing
a missing mixed-day path to date selection.

## Fixture and implementation constraints

The current [service-day fixture](../scripts/routing_service_day_fixture.py),
[anchor validator](../scripts/routing_service_day_anchor.py),
[worker](../scripts/_routing_service_day_anchor_worker.py) and
[street-index correction](../scripts/routing_street_index_correction.py) are
deliberately bounded to two stops and one ride. Preserve those fixtures,
fingerprints and guards. Increasing the ride limit alone does not supply a
reviewed third stop, its connector or a transfer oracle.

The implemented experiment selects the explicitly transit-only boundary:
artificial access to A and egress from C each cost twelve seconds; no other stop
is present in those maps. Interstop street transfers are temporarily replaced
with empty lists, with before/during/after snapshots and restoration checks.
The same-stop transfer at B remains available. Each boarding must satisfy the
pinned native rule `departure > preceding arrival + 60 seconds`.

The reviewed fictional street file still supports network construction, but this
experiment does not validate its three-stop walking linkage, geometry, walking
duration or public station access. Existing walking corrections are not enabled.
The native transit algorithm is unchanged; the deliberately altered transfer
table is an explicit fixture-model assumption, not a service-day repair.

Inspect native state chains before testing normal Python itinerary serialization.
The [source review](commute_service_day_selection_review.md) identifies a separate
midnight-base risk in serialization. A native search pass must not be promoted
to an end-to-end itinerary pass until returned dates, chronology, waits, transfer
durations and walking legs have independent checks.

## Later integration acceptance

The minimal fixture is a discriminating regression, not the complete production
contract. A general integration must also preserve the original twelve-case
expectations and cover overlapping service instances, midnight-spanning query
windows, calendar exceptions on both dates, date/DST boundaries and the full
source time range. Preserve the frozen source GTFS and its audited fingerprints.

Keep the work in the draft feature PR. A combined-service-day implementation and
real Melbourne routing remain separate steps after these evidence boundaries.
