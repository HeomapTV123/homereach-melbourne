"""Pinned transport snapshot contract shared by preflight and GIS processing."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .gtfs import read_json, require
from .service import WINDOWS, CATEGORY_FEED


SOURCE_HASH = "c88af3abcaf0872e45196dcc1d5af9bc20a82c54a00a9dfef46c809ec2e34814"
SERVICE_DATE = "2026-10-13"


def load_transport_snapshot(path: Path) -> dict[str, Any]:
    """Version 1 implements one audited date/snapshot, not an arbitrary feed API."""
    spec = read_json(path)
    pinned = {
        "schema_version": 1, "filename": "gtfs.zip", "sha256": SOURCE_HASH,
        "service_date": SERVICE_DATE, "timezone": "Australia/Melbourne",
        "feed_ids": ["2", "3", "4"], "point_epsg": 4326, "native_epsg": 7844,
        "match_epsg": 7855, "boundary_year": 2025, "near_boundary_metres": 10.0,
        "lga_count": 31, "replacement_label": "Replacement Bus",
        "rental_reporting_quarter": "2025Q3",
        "windows": {key: list(value) for key, value in WINDOWS.items()},
        "category_feed": CATEGORY_FEED,
        "location_counts": {"2": 2859, "3": 1623, "4": 22633},
        "platform_counts": {"2": 775, "3": 1623, "4": 22633},
        "active_trip_counts": {"2": 2828, "3": 5044, "4": 27708},
        "replacement_trip_counts": {"2": 52, "3": 0, "4": 0},
        "scan_rows": {"2": 688380, "3": 2568892, "4": 8589911},
        "spatial_counts": {"matched_within": 21426, "outside_selected_lgas": 3605},
        "near_boundary_count": 443,
        "expected_totals": {"source_rows":11847183,"active_trips":35580,"active_events":1311746,
                            "service_day_events":1175281,"am_events":158932,"am_trips":5768,"lga_rows":248},
        "outer_members": [f"{f}/google_transit.zip" for f in ("1","2","3","4","5","6","10","11")],
    }
    for key, expected in pinned.items():
        require(spec.get(key) == expected,
                f"Transport contract changed at {key}. Re-audit a new snapshot/method; do not bypass this check.")
    require(set(spec.get("feed_labels", {})) == set(spec["feed_ids"]), "Missing operational feed labels.")
    require(isinstance(spec.get("publisher_page"), str), "Missing publisher page.")
    return spec
