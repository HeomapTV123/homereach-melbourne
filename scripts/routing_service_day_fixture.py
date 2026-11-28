"""Fictional service-day boundary cases and an independent result oracle.

The street grid, stops and shapes are the reviewed smoke fixture. Only its
synthetic timetable changes. This module uses no engine or project datasets.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta
from io import StringIO
import math
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo

import routing_smoke_fixture as smoke_fixture


FIXTURE_ID = "homereach_service_day_boundary_v1"
TIMEZONE = "Australia/Melbourne"
SERVICE_DATE = "2026-10-13"
ORIGIN = smoke_fixture.ORIGIN
DESTINATION = smoke_fixture.DESTINATION
ORIGIN_ID = "synthetic_origin"
DESTINATION_ID = "synthetic_destination"
AGENCY_ID = smoke_fixture.AGENCY_ID
START_STOP_ID = smoke_fixture.START_STOP_ID
END_STOP_ID = smoke_fixture.END_STOP_ID
SHAPE_ID = smoke_fixture.SHAPE_ID
# The pinned R5 sampler divides the window by 60 draws: a one-minute window
# has a zero increment, while five minutes causes excessive resampling until
# exactly 60 samples are drawn. Six minutes avoids both without engine patches.
# https://github.com/r5py/r5/blob/v7.5.1-r5py/src/main/java/com/conveyal/r5/profile/McRaptorSuboptimalPathProfileRouter.java
QUERY_WINDOW_SECONDS = 360
MAX_PROBLEM_EXAMPLES = 12
GTFS_FILENAMES = (*smoke_fixture.GTFS_FILENAMES, "calendar_dates.txt")
street_xml = smoke_fixture.street_xml


def _case(identifier, departure, description, route=None, bus_departure=None, bus_arrival=None):
    return {"id": identifier, "departure": departure, "expected_route_id": route,
            "expected_bus_departure": bus_departure, "expected_bus_arrival": bus_arrival,
            "description": description}


# Expected calendar datetimes are explicit oracle values. They are not computed
# from the GTFS table generator or inferred from any returned engine result.
CASES = (
    _case("daytime_control", "2026-10-13T08:00:00", "Ordinary Tuesday service.",
          "SD_DAY", "2026-10-13T08:05:00", "2026-10-13T08:10:00"),
    _case("next_date_daytime_control", "2026-10-14T09:00:00", "Ordinary Wednesday service.",
          "SD_WEDNESDAY", "2026-10-14T09:05:00", "2026-10-14T09:10:00"),
    _case("daytime_calendar_addition", "2026-10-13T10:00:00", "Added Tuesday service during its own calendar date.",
          "SD_ADDED_DAY", "2026-10-13T10:05:00", "2026-10-13T10:10:00"),
    _case("daytime_calendar_removal", "2026-10-13T11:00:00", "Tuesday daytime service at 11:05 was removed."),
    _case("midnight_crossing", "2026-10-13T23:50:00", "Tuesday trip arriving after midnight.",
          "SD_CROSS_MIDNIGHT", "2026-10-13T23:58:00", "2026-10-14T00:03:00"),
    _case("previous_service_24h", "2026-10-14T00:10:00", "Previous service day at 24:15.",
          "SD_AFTER_24", "2026-10-14T00:15:00", "2026-10-14T00:20:00"),
    _case("previous_service_25h", "2026-10-14T01:00:00", "Previous service day at 25:05.",
          "SD_AFTER_25", "2026-10-14T01:05:00", "2026-10-14T01:10:00"),
    _case("previous_service_32h", "2026-10-14T08:37:00", "Previous service day through 32:47.",
          "SD_AFTER_32", "2026-10-14T08:42:00", "2026-10-14T08:47:00"),
    _case("calendar_addition", "2026-10-14T02:00:00", "Added Tuesday service at 26:05.",
          "SD_ADDED", "2026-10-14T02:05:00", "2026-10-14T02:10:00"),
    _case("calendar_removal", "2026-10-14T03:00:00", "Tuesday service at 27:05 was removed."),
    _case("same_date_must_not_wrap", "2026-10-13T01:00:00", "25:05 must not become Tuesday 01:05."),
    _case("inactive_date", "2026-10-15T01:00:00", "Tuesday 25:05 must not carry into Thursday."),
)


# Generator schedule: (route, service, trip, departure, arrival). These raw GTFS
# service-day strings intentionally retain hours above 24, independent of CASES.
_TRIPS = (
    ("SD_DAY", "SD_TUESDAY", "SD_TRIP_DAY", "08:05:00", "08:10:00"),
    ("SD_WEDNESDAY", "SD_WEDNESDAY", "SD_TRIP_WEDNESDAY", "09:05:00", "09:10:00"),
    ("SD_ADDED_DAY", "SD_ADDED", "SD_TRIP_ADDED_DAY", "10:05:00", "10:10:00"),
    ("SD_REMOVED_DAY", "SD_REMOVED", "SD_TRIP_REMOVED_DAY", "11:05:00", "11:10:00"),
    ("SD_CROSS_MIDNIGHT", "SD_TUESDAY", "SD_TRIP_CROSS", "23:58:00", "24:03:00"),
    ("SD_AFTER_24", "SD_TUESDAY", "SD_TRIP_24", "24:15:00", "24:20:00"),
    ("SD_AFTER_25", "SD_TUESDAY", "SD_TRIP_25", "25:05:00", "25:10:00"),
    ("SD_AFTER_32", "SD_TUESDAY", "SD_TRIP_32", "32:42:00", "32:47:00"),
    ("SD_ADDED", "SD_ADDED", "SD_TRIP_ADDED", "26:05:00", "26:10:00"),
    ("SD_REMOVED", "SD_REMOVED", "SD_TRIP_REMOVED", "27:05:00", "27:10:00"),
)


def _csv(header, rows) -> bytes:
    stream = StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def gtfs_tables() -> dict[str, bytes]:
    """Return nine deterministic tables with unchanged smoke stops and shapes."""
    tables = smoke_fixture.gtfs_tables()
    tables["agency.txt"] = _csv(
        ("agency_id", "agency_name", "agency_url", "agency_timezone", "agency_lang"),
        [(AGENCY_ID, "HomeReach Fictional Transit", "https://example.invalid/homereach-smoke",
          TIMEZONE, "en")],
    )
    tables["routes.txt"] = _csv(
        ("route_id", "agency_id", "route_short_name", "route_long_name", "route_type"),
        [(route, AGENCY_ID, route, "Fictional service-day boundary", "3")
         for route, *_ in _TRIPS],
    )
    tables["trips.txt"] = _csv(
        ("route_id", "service_id", "trip_id", "trip_headsign", "direction_id", "shape_id"),
        [(route, service, trip, "Fictional East", "0", SHAPE_ID)
         for route, service, trip, _, _ in _TRIPS],
    )
    times = []
    for _, _, trip, departure, arrival in _TRIPS:
        times.extend([
            (trip, departure, departure, START_STOP_ID, "1", "0", "0", "1"),
            (trip, arrival, arrival, END_STOP_ID, "2", "0", "0", "1"),
        ])
    tables["stop_times.txt"] = _csv(
        ("trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence",
         "pickup_type", "drop_off_type", "timepoint"), times,
    )
    tables["calendar.txt"] = _csv(
        ("service_id", "monday", "tuesday", "wednesday", "thursday", "friday",
         "saturday", "sunday", "start_date", "end_date"),
        [(service, "0", tuesday, wednesday, "0", "0", "0", "0", "20261012", "20261018")
         for service, tuesday, wednesday in (
             ("SD_TUESDAY", "1", "0"), ("SD_WEDNESDAY", "0", "1"),
             ("SD_ADDED", "0", "0"), ("SD_REMOVED", "1", "0"))],
    )
    tables["calendar_dates.txt"] = _csv(
        ("service_id", "date", "exception_type"),
        [("SD_ADDED", "20261013", "1"), ("SD_REMOVED", "20261013", "2")],
    )
    tables["feed_info.txt"] = _csv(
        ("feed_publisher_name", "feed_publisher_url", "feed_lang",
         "feed_start_date", "feed_end_date", "feed_version"),
        [("HomeReach synthetic service-day fixture", "https://example.invalid/homereach-smoke",
          "en", "20261012", "20261018", FIXTURE_ID)],
    )
    return tables


def write_gtfs(path: Path) -> None:
    """Write a new reproducible ZIP, preserving any existing destination."""
    tables = gtfs_tables()
    with ZipFile(path, mode="x", compression=ZIP_STORED) as archive:
        for name in GTFS_FILENAMES:
            info = ZipInfo(name, date_time=smoke_fixture.ZIP_TIMESTAMP)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = ZIP_STORED
            archive.writestr(info, tables[name])


def _finite(value, *, zero_allowed=False) -> bool:
    return (type(value) in (int, float) and math.isfinite(value)
            and (value >= 0 if zero_allowed else value > 0))


def _local_datetime(value) -> datetime:
    if not isinstance(value, str) or value != value.strip():
        raise ValueError("Expected an unpadded local ISO datetime string.")
    result = datetime.fromisoformat(value)
    if result.tzinfo is not None:
        raise ValueError("Expected the fixture's timezone-naive local datetime convention.")
    return result


class _Problems:
    def __init__(self):
        self.count = 0
        self.examples = []

    def add(self, text):
        self.count += 1
        if len(self.examples) < MAX_PROBLEM_EXAMPLES:
            self.examples.append(str(text)[:400])

    def result(self, options=0, buses=0):
        return {"status": "failed" if self.count else "passed", "options_checked": options,
                "bus_legs_checked": buses, "problem_count": self.count,
                "problems": self.examples}


def _check_option(case, option, legs, problems) -> int:
    """Inspect raw returned clocks; never adjust or reconstruct engine legs."""
    if sorted((row["segment"], row.get("mode")) for row in legs) != [
            (0, "WALK"), (1, "BUS"), (2, "WALK")]:
        problems.add(f"Option {option}: expected one complete WALK/BUS/WALK sequence.")
        return 0
    legs = sorted(legs, key=lambda row: row["segment"])
    departures = []
    arrivals = []
    for row in legs:
        if row.get("from_id") != ORIGIN_ID or row.get("to_id") != DESTINATION_ID:
            problems.add(f"Option {option}: origin/destination identity differs from the fixture.")
        duration, distance, wait = (row.get(name) for name in
                                    ("travel_time_seconds", "distance_m", "wait_time_seconds"))
        if not _finite(duration) or not _finite(distance) or not _finite(wait, zero_allowed=True):
            raise ValueError("Leg duration, distance or waiting time is invalid.")
        if row.get("geometry_nonempty") is not True:
            problems.add(f"Option {option}: a leg has no nonempty geometry.")
        departure = _local_datetime(row.get("departure_time"))
        departures.append(departure)
        arrivals.append(departure + timedelta(seconds=duration))
    query = _local_datetime(case["departure"])
    if not query <= departures[0] < query + timedelta(seconds=QUERY_WINDOW_SECONDS):
        problems.add(f"Option {option}: initial departure is outside the requested sample window.")
    for index in (1, 2):
        if departures[index] < arrivals[index - 1]:
            problems.add(f"Option {option}: segment {index} departs before the preceding arrival.")
    bus = legs[1]
    if (bus.get("agency_id"), bus.get("route_id"), bus.get("start_stop_id"),
            bus.get("end_stop_id")) != (AGENCY_ID, case["expected_route_id"], START_STOP_ID, END_STOP_ID):
        problems.add(f"Option {option}: bus agency, route or stop identity differs from the expected trip.")
    if departures[1] != _local_datetime(case["expected_bus_departure"]):
        problems.add(f"Option {option}: bus departure has the wrong service-day date or clock time.")
    if arrivals[1] != _local_datetime(case["expected_bus_arrival"]):
        problems.add(f"Option {option}: bus arrival has the wrong service-day date or clock time.")
    if not math.isclose(bus["travel_time_seconds"], 300.0, rel_tol=0.0, abs_tol=1e-6):
        problems.add(f"Option {option}: expected a five-minute bus ride.")
    gap = (departures[1] - arrivals[0]).total_seconds()
    if not math.isclose(bus["wait_time_seconds"], gap, rel_tol=0.0, abs_tol=1.0):
        problems.add(f"Option {option}: bus wait differs from the preceding arrival gap.")
    padding = (departures[2] - arrivals[1]).total_seconds()
    if not math.isclose(padding, 60.0, rel_tol=0.0, abs_tol=1.0):
        problems.add(f"Option {option}: expected the pinned integration's 60-second egress pad.")
    if any(legs[index]["wait_time_seconds"] != 0 for index in (0, 2)):
        problems.add(f"Option {option}: unexpected wait on an access or egress walk.")
    return 1


def validate_case(case: dict, rows: list) -> dict:
    """Require the exact fixed case's raw result, without a fixed option count.

    Positive cases require at least one complete itinerary. Negative controls
    require no returned itinerary, including walking fallback. Finding examples
    are bounded, but ``problem_count`` retains the full diagnostic count.
    """
    problems = _Problems()
    if not isinstance(case, dict) or case not in CASES:
        problems.add("Unknown or modified service-day fixture case.")
        return problems.result()
    if not isinstance(rows, list):
        problems.add("Returned itinerary rows must be a list.")
        return problems.result()
    if case["expected_route_id"] is None:
        if rows:
            problems.add("The inactive/removed-service control returned an itinerary.")
        return problems.result()
    if not rows:
        problems.add("The expected active bus itinerary is missing.")
        return problems.result()
    groups = {}
    for index, row in enumerate(rows):
        if (not isinstance(row, dict) or type(row.get("option")) is not int
                or row["option"] < 0 or type(row.get("segment")) is not int or row["segment"] < 0):
            problems.add(f"Returned row {index}: malformed option or segment identity.")
            continue
        groups.setdefault(row["option"], []).append(row)
    buses = 0
    for option, legs in groups.items():
        try:
            buses += _check_option(case, option, legs, problems)
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            problems.add(f"Option {option}: malformed itinerary: {error}")
    return problems.result(options=len(groups), buses=buses)
