"""Verify fictional network/calendar semantics without importing a routing engine."""
from __future__ import annotations

from collections import defaultdict, deque
import csv
from datetime import datetime
import importlib.util
from io import StringIO
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZIP_STORED, ZipFile

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/routing_smoke_fixture.py"
spec = importlib.util.spec_from_file_location("routing_smoke_fixture", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def read_tables():
    return {name: list(csv.DictReader(StringIO(value.decode("utf-8"))))
            for name, value in m.gtfs_tables().items()}


def test_street_grid_is_connected_and_preserves_every_adjacent_segment():
    root = ET.fromstring(m.street_xml())
    nodes = {int(node.attrib["id"]): node for node in root.findall("node")}
    ways = root.findall("way")
    assert set(nodes) == set(range(1, 50))
    assert len(ways) == 84
    assert len({way.attrib["id"] for way in ways}) == 84
    graph = defaultdict(set)
    edges = set()
    for way in ways:
        ids = [int(node.attrib["ref"]) for node in way.findall("nd")]
        assert len(ids) == 2
        assert set(ids) <= nodes.keys()
        edge = tuple(sorted(ids))
        assert edge not in edges
        edges.add(edge)
        first, second = ids
        first_row, first_column = divmod(first - 1, 7)
        second_row, second_column = divmod(second - 1, 7)
        assert abs(first_row - second_row) + abs(first_column - second_column) == 1
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in way.findall("tag")}
        assert tags["highway"] == "residential"
        assert tags["foot"] == "yes"
        assert tags["oneway"] == "no"
        assert "fictional" in tags["name"]
        graph[first].add(second)
        graph[second].add(first)
    visited = {1}
    queue = deque([1])
    while queue:
        for neighbour in graph[queue.popleft()]:
            if neighbour not in visited:
                visited.add(neighbour)
                queue.append(neighbour)
    assert visited == set(nodes)
    for identifier, node in nodes.items():
        row, column = divmod(identifier - 1, 7)
        assert float(node.attrib["lat"]) == pytest.approx(row * 0.006, abs=1e-9)
        assert float(node.attrib["lon"]) == pytest.approx(column * 0.006, abs=1e-9)


def test_gtfs_has_only_the_eight_expected_tables_and_consistent_references():
    tables = read_tables()
    assert set(tables) == {
        "agency.txt", "stops.txt", "routes.txt", "trips.txt", "stop_times.txt",
        "calendar.txt", "shapes.txt", "feed_info.txt",
    }
    agencies = {row["agency_id"] for row in tables["agency.txt"]}
    stops = {row["stop_id"] for row in tables["stops.txt"]}
    routes = {row["route_id"] for row in tables["routes.txt"]}
    services = {row["service_id"] for row in tables["calendar.txt"]}
    shapes = {row["shape_id"] for row in tables["shapes.txt"]}
    trips = {row["trip_id"] for row in tables["trips.txt"]}
    assert agencies == {"SMOKE"}
    assert stops == {"SMOKE_WEST", "SMOKE_EAST"}
    assert routes == {"SMOKE_BUS"}
    assert len(trips) == len(tables["trips.txt"]) == 3
    assert len(tables["stop_times.txt"]) == 6
    assert all(":" not in identifier
               for identifier in agencies | stops | routes | services | shapes | trips)
    assert all(row["agency_id"] in agencies and row["route_type"] == "3"
               for row in tables["routes.txt"])
    assert all(row["route_id"] in routes and row["service_id"] in services
               and row["shape_id"] in shapes for row in tables["trips.txt"])
    assert all(row["trip_id"] in trips and row["stop_id"] in stops
               for row in tables["stop_times.txt"])
    assert tables["agency.txt"][0]["agency_timezone"] == "Etc/UTC"


def test_active_and_inactive_query_dates_are_inside_calendar_but_different_service_days():
    tables = read_tables()
    calendar = tables["calendar.txt"][0]
    start = datetime.strptime(calendar["start_date"], "%Y%m%d").date()
    end = datetime.strptime(calendar["end_date"], "%Y%m%d").date()
    assert start.isoformat() == "2026-10-12"
    assert end.isoformat() == "2026-10-18"
    assert m.ACTIVE_DEPARTURE == datetime(2026, 10, 13, 8)
    assert m.INACTIVE_DEPARTURE == datetime(2026, 10, 14, 8)
    weekdays = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    for query, expected in ((m.ACTIVE_DEPARTURE, "1"), (m.INACTIVE_DEPARTURE, "0")):
        assert start <= query.date() <= end
        assert calendar[weekdays[query.weekday()]] == expected
    assert [day for day in weekdays if calendar[day] == "1"] == ["tuesday"]
    feed = tables["feed_info.txt"][0]
    assert feed["feed_start_date"] == calendar["start_date"]
    assert feed["feed_end_date"] == calendar["end_date"]


def test_schedule_has_monotonic_five_minute_trips_and_exact_departures():
    trips = defaultdict(list)
    for row in read_tables()["stop_times.txt"]:
        trips[row["trip_id"]].append(row)
    departures = []
    for rows in trips.values():
        rows.sort(key=lambda row: int(row["stop_sequence"]))
        assert [row["stop_id"] for row in rows] == ["SMOKE_WEST", "SMOKE_EAST"]
        assert [int(row["stop_sequence"]) for row in rows] == [1, 2]
        times = []
        for row in rows:
            arrival = datetime.strptime(row["arrival_time"], "%H:%M:%S")
            departure = datetime.strptime(row["departure_time"], "%H:%M:%S")
            assert arrival <= departure
            times.extend((arrival, departure))
        assert times == sorted(times)
        assert (times[-1] - times[0]).total_seconds() == 300
        departures.append(rows[0]["departure_time"])
    assert sorted(departures) == ["08:05:00", "08:10:00", "08:15:00"]


def test_stops_and_shape_follow_the_connected_grid_row_and_queries_are_near_stops():
    tables = read_tables()
    root = ET.fromstring(m.street_xml())
    node_coordinates = {(float(node.attrib["lon"]), float(node.attrib["lat"]))
                        for node in root.findall("node")}
    shape = sorted(tables["shapes.txt"], key=lambda row: int(row["shape_pt_sequence"]))
    shape_coordinates = [(float(row["shape_pt_lon"]), float(row["shape_pt_lat"]))
                         for row in shape]
    assert len(shape_coordinates) == 5
    assert set(shape_coordinates) <= node_coordinates
    assert [point[0] for point in shape_coordinates] == pytest.approx([0.006, 0.012, 0.018, 0.024, 0.030])
    assert all(point[1] == pytest.approx(0.018) for point in shape_coordinates)
    stops = {row["stop_id"]: (float(row["stop_lon"]), float(row["stop_lat"]))
             for row in tables["stops.txt"]}
    assert shape_coordinates[0] == stops["SMOKE_WEST"]
    assert shape_coordinates[-1] == stops["SMOKE_EAST"]
    assert m.ORIGIN == pytest.approx((0.0061, 0.018))
    assert m.DESTINATION == pytest.approx((0.0299, 0.018))
    assert abs(m.ORIGIN[0] - stops["SMOKE_WEST"][0]) < 0.0002
    assert abs(m.DESTINATION[0] - stops["SMOKE_EAST"][0]) < 0.0002


def test_zip_bytes_are_deterministic_and_each_member_contains_its_gtfs_table(tmp_path):
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    m.write_gtfs(first)
    m.write_gtfs(second)
    assert first.read_bytes() == second.read_bytes()
    with ZipFile(first) as archive:
        assert archive.namelist() == [
            "agency.txt", "stops.txt", "routes.txt", "trips.txt", "stop_times.txt",
            "calendar.txt", "shapes.txt", "feed_info.txt",
        ]
        for info in archive.infolist():
            assert info.date_time == (2026, 1, 1, 0, 0, 0)
            assert info.compress_type == ZIP_STORED
            assert info.create_system == 3
            assert info.external_attr == 0o100644 << 16
            assert archive.read(info.filename) == m.gtfs_tables()[info.filename]
        assert archive.testzip() is None


def test_zip_creation_preserves_existing_file(tmp_path):
    existing = tmp_path / "preserved.zip"
    existing.write_bytes(b"previous evidence")
    with pytest.raises(FileExistsError):
        m.write_gtfs(existing)
    assert existing.read_bytes() == b"previous evidence"
