from __future__ import annotations

import re

import pandas as pd

GTFS_TIME = re.compile(
    r"^(?P<hour>\d{1,2}):(?P<minute>\d{2}):(?P<second>\d{2})$"
)


def gtfs_time_to_seconds(value: object) -> int | pd.NA:
    """
    Convert a GTFS time to seconds after midnight.

    GTFS permits times greater than 24:00:00 for after-midnight services,
    so datetime.time is not suitable for raw parsing.
    """
    if value is None or pd.isna(value):
        return pd.NA

    match = GTFS_TIME.match(str(value).strip())
    if not match:
        return pd.NA

    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    second = int(match.group("second"))

    if minute > 59 or second > 59:
        return pd.NA

    return hour * 3600 + minute * 60 + second


def add_departure_seconds(stop_times: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with a nullable integer departure-time column."""
    required = {"trip_id", "stop_id", "departure_time"}
    missing = required.difference(stop_times.columns)
    if missing:
        raise ValueError(f"Missing stop_times columns: {sorted(missing)}")

    result = stop_times.copy()
    result["departure_seconds"] = (
        result["departure_time"]
        .map(gtfs_time_to_seconds)
        .astype("Int64")
    )
    return result
