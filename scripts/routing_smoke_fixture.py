"""Deterministic fictional streets and timetable for the isolated engine test.

Coordinates describe an invented grid near (0, 0), not Melbourne streets.
The XML is the reviewed source for a small committed PBF; generating the
GTFS ZIP at runtime needs only Python's standard library.
"""
from __future__ import annotations

import csv
from datetime import datetime
from io import StringIO
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZIP_STORED, ZipFile, ZipInfo


ACTIVE_DEPARTURE = datetime(2026, 10, 13, 8, 0)
INACTIVE_DEPARTURE = datetime(2026, 10, 14, 8, 0)
# Coordinate tuples use (longitude, latitude), matching point geometry APIs.
ORIGIN = (0.0061, 0.018)
DESTINATION = (0.0299, 0.018)
AGENCY_ID = "SMOKE"
ROUTE_ID = "SMOKE_BUS"
START_STOP_ID = "SMOKE_WEST"
END_STOP_ID = "SMOKE_EAST"
SERVICE_ID = "SMOKE_TUESDAY"
SHAPE_ID = "SMOKE_EASTBOUND"
GRID_SIZE = 7
GRID_SPACING = 0.006
GTFS_FILENAMES = (
    "agency.txt", "stops.txt", "routes.txt", "trips.txt",
    "stop_times.txt", "calendar.txt", "shapes.txt", "feed_info.txt",
)
ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)


def street_xml() -> bytes:
    """Return a connected 7-by-7 grid with one way per adjacent node pair."""
    root = ET.Element("osm", version="0.6", generator="HomeReach fictional smoke fixture")
    ET.SubElement(root, "bounds", minlat="0.0000000", minlon="0.0000000",
                  maxlat="0.0360000", maxlon="0.0360000")
    for row in range(GRID_SIZE):
        for column in range(GRID_SIZE):
            ET.SubElement(root, "node", id=str(row * GRID_SIZE + column + 1),
                          version="1", lat=f"{row * GRID_SPACING:.7f}",
                          lon=f"{column * GRID_SPACING:.7f}")

    way_id = 1001
    for row in range(GRID_SIZE):
        for column in range(GRID_SIZE):
            start = row * GRID_SIZE + column + 1
            neighbours = []
            if column + 1 < GRID_SIZE:
                neighbours.append(start + 1)
            if row + 1 < GRID_SIZE:
                neighbours.append(start + GRID_SIZE)
            for end in neighbours:
                way = ET.SubElement(root, "way", id=str(way_id), version="1")
                ET.SubElement(way, "nd", ref=str(start))
                ET.SubElement(way, "nd", ref=str(end))
                for key, value in (("highway", "residential"), ("foot", "yes"),
                                   ("oneway", "no"), ("name", "HomeReach fictional grid")):
                    ET.SubElement(way, "tag", k=key, v=value)
                way_id += 1
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def _csv(header: tuple[str, ...], rows: list[tuple]) -> bytes:
    text = StringIO(newline="")
    writer = csv.writer(text, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return text.getvalue().encode("utf-8")


def gtfs_tables() -> dict[str, bytes]:
    """Return eight self-contained GTFS tables for three Tuesday bus trips."""
    trip_rows = []
    time_rows = []
    for minute in (5, 10, 15):
        trip_id = f"SMOKE_TRIP_08{minute:02d}"
        departure = f"08:{minute:02d}:00"
        arrival = f"08:{minute + 5:02d}:00"
        trip_rows.append((ROUTE_ID, SERVICE_ID, trip_id, "Fictional East", "0", SHAPE_ID))
        time_rows.extend([
            (trip_id, departure, departure, START_STOP_ID, "1", "0", "0", "1"),
            (trip_id, arrival, arrival, END_STOP_ID, "2", "0", "0", "1"),
        ])
    return {
        "agency.txt": _csv(
            ("agency_id", "agency_name", "agency_url", "agency_timezone", "agency_lang"),
            [(AGENCY_ID, "HomeReach Fictional Transit", "https://example.invalid/homereach-smoke",
              "Etc/UTC", "en")],
        ),
        "stops.txt": _csv(
            ("stop_id", "stop_name", "stop_lat", "stop_lon", "location_type"),
            [(START_STOP_ID, "Fictional West", "0.0180000", "0.0060000", "0"),
             (END_STOP_ID, "Fictional East", "0.0180000", "0.0300000", "0")],
        ),
        "routes.txt": _csv(
            ("route_id", "agency_id", "route_short_name", "route_long_name", "route_type"),
            [(ROUTE_ID, AGENCY_ID, "SMOKE", "Fictional West to East", "3")],
        ),
        "trips.txt": _csv(
            ("route_id", "service_id", "trip_id", "trip_headsign", "direction_id", "shape_id"),
            trip_rows,
        ),
        "stop_times.txt": _csv(
            ("trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence",
             "pickup_type", "drop_off_type", "timepoint"),
            time_rows,
        ),
        "calendar.txt": _csv(
            ("service_id", "monday", "tuesday", "wednesday", "thursday", "friday",
             "saturday", "sunday", "start_date", "end_date"),
            [(SERVICE_ID, "0", "1", "0", "0", "0", "0", "0", "20261012", "20261018")],
        ),
        "shapes.txt": _csv(
            ("shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"),
            [(SHAPE_ID, "0.0180000", f"{column * GRID_SPACING:.7f}", str(column))
             for column in range(1, 6)],
        ),
        "feed_info.txt": _csv(
            ("feed_publisher_name", "feed_publisher_url", "feed_lang",
             "feed_start_date", "feed_end_date", "feed_version"),
            [("HomeReach synthetic smoke fixture", "https://example.invalid/homereach-smoke",
              "en", "20261012", "20261018", "synthetic-1")],
        ),
    }


def write_gtfs(path: Path) -> None:
    """Create a new deterministic GTFS ZIP; existing files are never replaced."""
    tables = gtfs_tables()
    with ZipFile(path, mode="x", compression=ZIP_STORED) as archive:
        for name in GTFS_FILENAMES:
            info = ZipInfo(name, date_time=ZIP_TIMESTAMP)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = ZIP_STORED
            archive.writestr(info, tables[name])
