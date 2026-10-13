"""Small-table reader and pure calendar/trip selection, refactored from notebook 07."""
from __future__ import annotations
from datetime import date, datetime
from pathlib import Path
from typing import Any
from contextlib import contextmanager
from tempfile import SpooledTemporaryFile
from zipfile import ZipFile
import hashlib
import json
import shutil
import pandas as pd

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
TABLE_NAMES = ("agency.txt", "routes.txt", "trips.txt", "calendar.txt", "calendar_dates.txt", "stops.txt")
REQUIRED_COLUMNS = {
    "agency.txt": {"agency_id", "agency_timezone"},
    "routes.txt": {"route_id", "agency_id", "route_short_name", "route_long_name", "route_type"},
    "trips.txt": {"trip_id", "route_id", "service_id"},
    "calendar.txt": {"service_id", "start_date", "end_date", *DAYS},
    "calendar_dates.txt": {"service_id", "date", "exception_type"},
    "stops.txt": {"stop_id", "stop_name", "stop_lat", "stop_lon", "location_type", "parent_station", "wheelchair_boarding"},
}

def require(condition: bool, message: str) -> None:
    if not bool(condition):
        raise ValueError(message)

def sha256_file(path: str | Path) -> str:
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()

def read_json(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    require(isinstance(data, dict), f"Expected a JSON object in {path}")
    return data

@contextmanager
def open_feed(path: Path, feed_id: str):
    """Read a nested archive without extracting paths. Spool large members to OS temp."""
    member = f"{feed_id}/google_transit.zip"
    with ZipFile(path) as outer, SpooledTemporaryFile(max_size=16*1024*1024, mode="w+b") as spool:
        require(len(outer.namelist()) == len(set(outer.namelist())), "Duplicate outer ZIP member.")
        require(outer.namelist().count(member) == 1, f"Missing or duplicate feed: {member}")
        with outer.open(member) as handle:
            shutil.copyfileobj(handle, spool, length=1024*1024)
        spool.seek(0)
        with ZipFile(spool) as inner:
            require(len(inner.namelist()) == len(set(inner.namelist())), "Duplicate inner ZIP member.")
            require("frequencies.txt" not in inner.namelist(), "Frequency-based trips require a reviewed extension.")
            yield inner

def read_feed_tables(path: Path, feed_id: str) -> dict[str, pd.DataFrame]:
    tables = {}
    with open_feed(path, feed_id) as inner:
        for name in TABLE_NAMES:
            require(inner.namelist().count(name) == 1, f"Feed {feed_id}: missing {name}")
            with inner.open(name) as handle:
                frame = pd.read_csv(handle, dtype="string", keep_default_na=False, encoding="utf-8-sig", low_memory=False)
            require(REQUIRED_COLUMNS[name].issubset(frame.columns), f"Feed {feed_id}: missing columns in {name}")
            tables[name] = frame
    return tables

def require_key(frame: pd.DataFrame, columns: list[str], label: str) -> None:
    """Require complete, unpadded identifiers and a unique primary key."""
    require(set(columns).issubset(frame.columns), f"{label}: missing key columns.")
    for column in columns:
        values = frame[column].astype("string")
        require(
            values.notna().all() and values.ne("").all()
            and values.eq(values.str.strip()).all(),
            f"{label}: blank or padded identifier in {column}.",
        )
    require(not frame.duplicated(columns).any(), f"{label}: duplicate key {columns}.")

def validate_gtfs_dates(values: pd.Series, label: str) -> None:
    text = values.astype("string")
    require(
        text.notna().all() and text.str.fullmatch(r"[0-9]{8}").all(),
        f"{label}: expected complete YYYYMMDD strings.",
    )
    for value in text.unique():
        try:
            datetime.strptime(str(value), "%Y%m%d")
        except ValueError as error:
            raise ValueError(f"{label}: invalid date {value!r}.") from error

def active_service_ids(
    calendar: pd.DataFrame | None,
    exceptions: pd.DataFrame | None,
    service_date: date,
) -> set[str]:
    """Select IDs within one feed, including exception-only service."""
    require(type(service_date) is date, "Use a date object for the local GTFS service day.")
    date_key = service_date.strftime("%Y%m%d")
    weekday = DAYS[service_date.weekday()]
    base, additions, removals = set(), set(), set()

    if calendar is not None and not calendar.empty:
        require(REQUIRED_COLUMNS["calendar.txt"].issubset(calendar.columns), "Missing calendar columns.")
        require_key(calendar, ["service_id"], "calendar")
        validate_gtfs_dates(calendar["start_date"], "calendar start")
        validate_gtfs_dates(calendar["end_date"], "calendar end")
        require(calendar["start_date"].le(calendar["end_date"]).all(), "Reversed calendar date interval.")
        for day in DAYS:
            require(calendar[day].isin(["0", "1"]).all(), f"Invalid weekday flag: {day}.")
        base = set(calendar.loc[
            calendar["start_date"].le(date_key)
            & calendar["end_date"].ge(date_key)
            & calendar[weekday].eq("1"),
            "service_id",
        ])

    if exceptions is not None and not exceptions.empty:
        require(REQUIRED_COLUMNS["calendar_dates.txt"].issubset(exceptions.columns), "Missing exception columns.")
        require_key(exceptions, ["service_id", "date"], "calendar exceptions")
        validate_gtfs_dates(exceptions["date"], "calendar exception")
        require(exceptions["exception_type"].isin(["1", "2"]).all(), "Unexpected calendar exception type.")
        relevant = exceptions.loc[exceptions["date"].eq(date_key)]
        additions = set(relevant.loc[relevant["exception_type"].eq("1"), "service_id"])
        removals = set(relevant.loc[relevant["exception_type"].eq("2"), "service_id"])

    return (base | additions) - removals

def build_active_trips(feed_tables: dict, service_date: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Select trips per feed and preserve all source trip fields and namespaced keys."""
    parts = []
    summary_rows = []
    for feed_id in tuple(feed_tables):
        tables = feed_tables[feed_id]
        trips = tables["trips.txt"]
        routes = tables["routes.txt"]
        require(set(tables["agency.txt"]["agency_timezone"]) == {"Australia/Melbourne"}, "Unexpected agency timezone.")
        calendar = tables["calendar.txt"]
        exceptions = tables["calendar_dates.txt"]

        require_key(trips, ["trip_id"], f"feed {feed_id}/trips")
        require_key(routes, ["route_id"], f"feed {feed_id}/routes")
        require(trips["route_id"].isin(routes["route_id"]).all(), f"Unknown trip-to-route reference in feed {feed_id}.")
        all_defined_services = set(calendar["service_id"]) | set(exceptions["service_id"])
        require(trips["service_id"].isin(all_defined_services).all(), f"Unknown service ID in feed {feed_id}.")

        service_ids = active_service_ids(calendar, exceptions, service_date)
        selected = trips.loc[trips["service_id"].isin(service_ids)].copy()
        selected_before_join = selected.copy(deep=True)
        selected = selected.merge(
            routes[["route_id", "route_short_name", "route_long_name", "route_type"]],
            on="route_id", how="left", validate="many_to_one", indicator=True,
        )
        require(selected["_merge"].eq("both").all(), f"A selected trip has no route in feed {feed_id}.")
        selected = selected.drop(columns="_merge")
        # Every source trip field must survive the route join unchanged.
        pd.testing.assert_frame_equal(
            selected[list(trips.columns)].sort_values("trip_id").reset_index(drop=True),
            selected_before_join.sort_values("trip_id").reset_index(drop=True),
            check_exact=True,
        )

        selected["feed_id"] = pd.Series(feed_id, index=selected.index, dtype="string")
        selected["service_date"] = service_date.isoformat()
        selected["agency_timezone"] = "Australia/Melbourne"
        selected["trip_key"] = feed_id + ":" + selected["trip_id"]
        selected["route_key"] = feed_id + ":" + selected["route_id"]
        selected["service_key"] = feed_id + ":" + selected["service_id"]
        selected["is_labelled_replacement_bus"] = selected["route_short_name"].str.casefold().eq("replacement bus")
        replacement_count = int(selected["is_labelled_replacement_bus"].sum())

        parts.append(selected)
        summary_rows.append({
            "feed_id": feed_id,
            "active_trip_records": len(selected),
            "labelled_replacement_trip_records": replacement_count,
        })

    active_trips = (
        pd.concat(parts, ignore_index=True)
        .sort_values(["feed_id", "trip_id"], kind="stable")
        .reset_index(drop=True)
    )
    require(not active_trips.duplicated(["feed_id", "trip_id"]).any(), "Duplicate feed/trip key.")
    require(active_trips["trip_key"].is_unique, "Prefixed trip key is not unique.")
    require(active_trips["service_date"].eq(service_date.isoformat()).all(), "Mixed service dates.")

    return active_trips, pd.DataFrame(summary_rows)
