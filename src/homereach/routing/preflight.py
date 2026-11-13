"""Read-only input preflight for one historical scheduled-commute pilot.

This checks the pinned GTFS archive, small tables and stop-time headers. It
does not scan stop-time rows, build a street network or compute journeys.
Existing nested-ZIP helpers may spool bytes to operating-system temporary
storage; no source files are extracted and no project files are written.
"""
from __future__ import annotations

import csv
from datetime import date
import io
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from typing import Any
from zipfile import BadZipFile, ZipFile

import pandas as pd

from homereach.transport.gtfs import (
    build_active_trips, open_feed, read_feed_tables, require, sha256_file,
)
from homereach.transport.snapshot import load_transport_snapshot
from homereach.transport.service import RAW_EVENT_COLUMNS


PILOT_CONFIG_PATH = "config/routing_pilot.json"
PILOT_FIELDS = {
    "schema_version", "pilot_id", "stage", "gtfs_snapshot_path", "gtfs_path",
    "service_date", "timezone", "feed_ids", "departure_times", "street_network",
    "locations",
}
NOT_VALIDATED = [
    "Stop-time rows, their references and complete journey timing.",
    "Street-network contents, walking connectivity and access/egress.",
    "Reviewed origin/destination locations and their network coverage.",
    "Routing-engine compatibility, transfers, journeys and travel times.",
]


def _project_path(root: Path, value: object, label: str) -> Path:
    """Resolve a project-relative POSIX path without permitting an escape."""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a nonempty project-relative path.")
    require(bool(value) and value == value.strip(),
            f"{label} must be a nonempty project-relative path.")
    require("\\" not in value and ":" not in value,
            f"{label} must use a safe project-relative path with forward slashes.")
    relative = PurePosixPath(value)
    require(not relative.is_absolute() and not PureWindowsPath(value).drive
            and relative.parts and all(part not in (".", "..") for part in relative.parts)
            and str(relative) == value,
            f"{label} must be a safe project-relative path.")
    resolved = (root / value).resolve()
    require(resolved.is_relative_to(root), f"{label} resolves outside the project.")
    return resolved


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate pilot configuration key: {key}.")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"Nonfinite pilot configuration value: {value}.")


def _load_inputs(project_root: Path) -> tuple[Path, dict, dict, Path]:
    root = Path(project_root).resolve()
    require(root.is_dir(), f"Project directory is missing: {root}")
    path = _project_path(root, PILOT_CONFIG_PATH, "pilot configuration")
    try:
        config = json.loads(path.read_text(encoding="utf-8-sig"),
                            object_pairs_hook=_unique_object,
                            parse_constant=_reject_constant)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read pilot configuration: {path}: {error}") from error
    require(isinstance(config, dict) and set(config) == PILOT_FIELDS,
            "Pilot configuration must contain exactly the reviewed version-1 fields.")
    require(type(config["schema_version"]) is int and config["schema_version"] == 1,
            "Unsupported pilot schema_version.")
    require(config["pilot_id"] == "melbourne_commute_pilot_v1", "Unexpected pilot_id.")
    require(config["stage"] == "input_preflight", "Only the input_preflight stage is supported.")
    require(config["street_network"] is None and config["locations"] is None,
            "Non-null street_network or locations require a reviewed extension; they are not validated by this preflight.")
    snapshot_path = _project_path(root, config["gtfs_snapshot_path"], "gtfs_snapshot_path")
    _project_path(root, config["gtfs_path"], "gtfs_path")
    try:
        snapshot = load_transport_snapshot(snapshot_path)
    except (OSError, UnicodeError, KeyError, TypeError) as error:
        raise ValueError(f"Cannot read the audited GTFS snapshot: {error}") from error
    for field in ("service_date", "timezone", "feed_ids"):
        require(config[field] == snapshot[field], f"Pilot {field} differs from the audited GTFS snapshot.")
    try:
        parsed_date = date.fromisoformat(config["service_date"])
    except (TypeError, ValueError) as error:
        raise ValueError("Pilot service_date must be an ISO calendar date.") from error
    require(parsed_date.isoformat() == config["service_date"], "Pilot service_date must use YYYY-MM-DD.")
    times = config["departure_times"]
    require(isinstance(times, list) and bool(times), "departure_times must be a nonempty list.")
    require(all(isinstance(value, str) and re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]", value)
                for value in times), "departure_times must contain HH:MM:SS local clock times.")
    require(times == sorted(set(times)), "departure_times must be ordered and unique.")
    start, end = snapshot["windows"]["am_peak_0700_0900"]
    for value in times:
        hour, minute, second = map(int, value.split(":"))
        require(start <= hour * 3600 + minute * 60 + second < end,
                "A departure time lies outside the audited 07:00-inclusive to 09:00-exclusive window.")
    return root, config, snapshot, snapshot_path


def load_pilot_config(project_root: Path) -> dict[str, Any]:
    """Validate the pilot and referenced pinned snapshot without reading raw GTFS."""
    return _load_inputs(project_root)[1]


def _stop_time_header(path: Path, feed_id: str) -> list[str]:
    with open_feed(path, feed_id) as archive:
        require(archive.namelist().count("stop_times.txt") == 1,
                f"Feed {feed_id}: missing stop_times.txt.")
        with archive.open("stop_times.txt") as binary:
            with io.TextIOWrapper(binary, encoding="utf-8-sig", newline="") as text:
                header = next(csv.reader(text), None)
        if not header:
            raise ValueError(f"Feed {feed_id}: missing stop-time header.")
        require(len(header) == len(set(header)),
                f"Feed {feed_id}: duplicate stop-time header columns.")
        require(all(value and value == value.strip() for value in header),
                f"Feed {feed_id}: blank or padded stop-time header column.")
        require(set(RAW_EVENT_COLUMNS).issubset(header),
                f"Feed {feed_id}: missing audited stop-time fields.")
    return header


def _inspect_gtfs(path: Path, snapshot: dict) -> dict[str, Any]:
    require(path.is_file(), f"GTFS path is not a regular file: {path}")
    digest = sha256_file(path)
    require(digest == snapshot["sha256"], "GTFS fingerprint differs from the audited source.")
    with ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), "Duplicate outer ZIP member.")
        require(set(names) == set(snapshot["outer_members"]), "GTFS outer archive inventory differs.")
    tables, headers = {}, {}
    for feed_id in snapshot["feed_ids"]:
        tables[feed_id] = read_feed_tables(path, feed_id)
        headers[feed_id] = _stop_time_header(path, feed_id)
    _, counts = build_active_trips(tables, date.fromisoformat(snapshot["service_date"]))
    by_feed = counts.set_index("feed_id")
    feeds = []
    for feed_id in snapshot["feed_ids"]:
        active = int(by_feed.loc[feed_id, "active_trip_records"])
        replacements = int(by_feed.loc[feed_id, "labelled_replacement_trip_records"])
        require(active == snapshot["active_trip_counts"][feed_id],
                f"Feed {feed_id}: active-trip count differs from the audited service date.")
        require(replacements == snapshot["replacement_trip_counts"][feed_id],
                f"Feed {feed_id}: labelled-replacement count differs from the audit.")
        feeds.append({"feed_id": feed_id, "active_trip_records": active,
                      "labelled_replacement_trip_records": replacements,
                      "stop_times_header": headers[feed_id]})
    require(sha256_file(path) == digest, "GTFS source changed during preflight.")
    return {"status": "verified", "sha256": digest, "feeds": feeds}


def check_routing_inputs(project_root: Path) -> dict[str, Any]:
    """Inspect available inputs and report blockers; never claim routing readiness.

    Invalid configuration or an invalid present archive raises ValueError.
    Missing raw input is reported without creating it. Version 1 always remains
    blocked because street-network and location reviews are outside its scope.
    """
    root, config, snapshot, snapshot_path = _load_inputs(project_root)
    config_path = _project_path(root, PILOT_CONFIG_PATH, "pilot configuration")
    protected = {path: sha256_file(path) for path in (config_path, snapshot_path)}
    gtfs_path = _project_path(root, config["gtfs_path"], "gtfs_path")
    checks = ["Pilot configuration matches the audited GTFS snapshot, service date and morning window."]
    blockers = []
    if not gtfs_path.exists():
        gtfs = {"status": "missing", "sha256": None, "feeds": []}
        blockers.append(f"Missing audited GTFS input: {config['gtfs_path']}.")
    else:
        try:
            gtfs = _inspect_gtfs(gtfs_path, snapshot)
        except (OSError, BadZipFile, UnicodeError, csv.Error, pd.errors.ParserError,
                pd.errors.EmptyDataError, KeyError, TypeError, AssertionError) as error:
            raise ValueError(f"Invalid GTFS input: {error}") from error
        checks.extend([
            "GTFS fingerprint and complete outer archive inventory match the audited snapshot.",
            "Selected nested feeds, small-table schemas and stop-time headers were checked.",
            "Active-trip and labelled-replacement counts match after applying calendar exceptions.",
            "GTFS source fingerprint is unchanged after reading.",
        ])
    gtfs["path"] = config["gtfs_path"]
    blockers.extend([
        "A reviewed street-network source and snapshot have not been configured.",
        "Reviewed origin/destination locations have not been configured.",
    ])
    for path, digest in protected.items():
        require(path.is_file() and sha256_file(path) == digest, "Pilot configuration or GTFS snapshot changed during preflight.")
    return {
        "schema_version": 1, "pilot_id": config["pilot_id"], "stage": "input_preflight",
        "status": "blocked", "service_date": config["service_date"],
        "timezone": config["timezone"], "departure_times": config["departure_times"],
        "gtfs": gtfs, "checks": checks, "blockers": blockers,
        "not_validated": list(NOT_VALIDATED), "project_files_written": 0,
        "journeys_computed": 0,
    }
