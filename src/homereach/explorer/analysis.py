"""Reusable comparison logic from notebook 08.

No notebook execution, raw GTFS scan, imputation or scoring occurs here.
This version intentionally retains the reviewed 2025Q3 / 2026-10-13 scope.
"""
from __future__ import annotations
from pathlib import Path
import hashlib
import json
from typing import Any
import numpy as np
import pandas as pd
from homereach.io.dffh_rent import COLUMN_ORDER, KEY_COLUMNS, read_panel_csv, load_snapshot

def require(condition, message):
    if not condition:
        raise ValueError(message)


def fingerprint(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def read_json(path):
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    require(isinstance(value, dict), f"Expected a JSON object: {path}")
    return value


def require_key(frame, columns, label):
    require(set(columns).issubset(frame.columns), f"{label}: missing key columns.")
    require(frame[columns].notna().all().all(), f"{label}: null key.")
    require(all(frame[c].astype("string").str.strip().ne("").all() for c in columns), f"{label}: empty key.")
    require(not frame.duplicated(columns).any(), f"{label}: duplicate key {columns}.")


def count_columns(frame, columns, label):
    frame = frame.copy()
    for column in columns:
        require(column in frame, f"{label}: missing {column}.")
        value = pd.to_numeric(frame[column], errors="raise")
        array = value.to_numpy(dtype=float)
        require(np.isfinite(array).all() and (array >= 0).all() and (array % 1 == 0).all(),
                f"{label}: {column} must contain finite, non-negative whole counts.")
        frame[column] = value.astype("int64")
    return frame


def complete_one_to_one(left, right, key, label):
    require_key(left, [key], f"{label} left")
    require_key(right, [key], f"{label} right")
    require(set(left[key]) == set(right[key]), f"{label}: different or missing keys; do not fill missing matches with zero.")
    overlap = (set(left.columns) & set(right.columns)) - {key}
    require(not overlap, f"{label}: unexpected overlapping columns {sorted(overlap)}.")
    result = left.merge(right, on=key, how="left", validate="one_to_one", indicator="_join_status")
    require(result["_join_status"].eq("both").all(), f"{label}: unmatched rows.")
    return result.drop(columns="_join_status")


def safe_ratio(numerator, denominator):
    # Undefined denominators stay missing; they are not converted to zero.
    return numerator.astype(float).div(denominator.astype(float).where(denominator.gt(0)))


AM_WINDOW = "am_peak_0700_0900"
DAY_WINDOW = "service_day"
CODE = "lga_code_2025"
SERVICE_DATE = "2026-10-13"
TIMEZONE = "Australia/Melbourne"
RENT_QUARTER = "2025Q3"
CATEGORY_FEED = {
    "train_not_labelled_replacement": "2", "labelled_replacement_bus": "2",
    "tram": "3", "myki_bus": "4",
}
CATEGORY_LABELS = {
    "train_not_labelled_replacement": "Train feed (not labelled replacement)",
    "labelled_replacement_bus": "Labelled replacement bus", "tram": "Tram", "myki_bus": "Myki bus",
}
COUNT_FIELDS = ["eligible_departure_events", "unique_trip_records", "served_stop_records",
                "unique_route_records", "near_boundary_events", "extended_time_events"]
GROUP = [CODE, "feed_id", "service_category", "window"]
def aggregate_lgas(lga_table, trip_memberships, stop_table, codes, window):
    selected = lga_table.loc[lga_table.window.eq(window)]
    require(set(selected[CODE]) == set(codes), "Incomplete LGA input for aggregation.")
    trips = trip_memberships.loc[trip_memberships.window.eq(window)]
    stops = stop_table.loc[stop_table.window.eq(window)]
    result = pd.DataFrame({CODE: sorted(codes)}).set_index(CODE)
    result["departure_events"] = selected.groupby(CODE).eligible_departure_events.sum().reindex(result.index, fill_value=0)
    result["unique_trip_records"] = trips.groupby(CODE).trip_key.nunique().reindex(result.index, fill_value=0)
    result["served_stop_records"] = stops.groupby(CODE).stop_key.nunique().reindex(result.index, fill_value=0)
    result["unique_route_records"] = trips.groupby(CODE).route_key.nunique().reindex(result.index, fill_value=0)
    result["near_boundary_events"] = selected.groupby(CODE).near_boundary_events.sum().reindex(result.index, fill_value=0)
    result["extended_time_events"] = selected.groupby(CODE).extended_time_events.sum().reindex(result.index, fill_value=0)
    return result.astype("int64").reset_index()


def attach_history_codes(panel: pd.DataFrame, crosswalk: pd.DataFrame) -> pd.DataFrame:
    """Attach only 2025 code/name identifiers; never backfill 2026 services into history."""
    require_key(panel, KEY_COLUMNS, "rental history")
    require_key(crosswalk, ["rental_area_name"], "crosswalk")
    require_key(crosswalk, [CODE], "crosswalk codes")
    require(set(panel.rental_area_name) == set(crosswalk.rental_area_name), "History/crosswalk areas differ.")
    result = panel.merge(crosswalk[["rental_area_name", CODE, "abs_lga_name", "boundary_year"]],
                         on="rental_area_name", how="left", validate="many_to_one")
    result = result.sort_values([CODE, "quarter_end"], kind="stable").reset_index(drop=True)
    pd.testing.assert_frame_equal(result[COLUMN_ORDER].sort_values(KEY_COLUMNS).reset_index(drop=True),
                                  panel[COLUMN_ORDER].sort_values(KEY_COLUMNS).reset_index(drop=True), check_exact=True)
    return result


def filter_comparison(frame: pd.DataFrame, *, regions: list[str] | None = None,
                      maximum_rent: float | None = None, minimum_am_trips: int = 0,
                      sort_by: str = "rental_area_name", ascending: bool = True) -> pd.DataFrame:
    """Descriptive filters, not eligibility for available properties or a recommendation."""
    allowed = {"rental_area_name", "median_weekly_rent", "am_unique_trip_records", "am_departure_events"}
    require(sort_by in allowed, "Unsupported sort field.")
    require(isinstance(minimum_am_trips, (int, np.integer)) and not isinstance(minimum_am_trips, bool)
            and minimum_am_trips >= 0, "Minimum trips must be a non-negative whole count.")
    mask = frame.am_unique_trip_records.ge(minimum_am_trips)
    if maximum_rent is not None:
        require(np.isfinite(maximum_rent) and maximum_rent >= 0, "Rent ceiling must be finite and non-negative.")
        mask &= frame.median_weekly_rent.le(maximum_rent)
    if regions is not None:
        require(set(regions).issubset(set(frame.source_region)), "Unknown source region.")
        mask &= frame.source_region.isin(regions)
    columns = [sort_by] if sort_by == "rental_area_name" else [sort_by, "rental_area_name"]
    directions = [ascending] if len(columns) == 1 else [ascending, True]
    return frame.loc[mask].sort_values(columns, ascending=directions, kind="stable").reset_index(drop=True).copy()


def load_inputs(root: Path) -> dict[str, Any]:
    ROOT = Path(root).resolve()
    TRANSPORT = ROOT / "data/processed/transport"
    REPORT_PATH = TRANSPORT / "transport_pipeline_report.json"
    GEO_REPORT_PATH = ROOT / "data/interim/geography/geography_pipeline_report.json"
    CROSSWALK_PATH = ROOT / "data/interim/geography/lga_crosswalk_2025.csv"
    RENT_PATH = ROOT / "data/processed/rent_quarterly.csv"
    RENT_REPORT_PATH = ROOT / "data/processed/rent_quality_report.json"
    SPEC_PATH = ROOT / "config/gtfs_snapshot.json"
    RENT_SPEC_PATH = ROOT / "config/rent_snapshot.json"
    GEO_SPEC_PATH = ROOT / "config/lga_snapshot.json"
    ALIAS_PATH = ROOT / "config/lga_name_aliases_2025.csv"
    base_paths = [REPORT_PATH, GEO_REPORT_PATH, CROSSWALK_PATH, RENT_PATH, RENT_REPORT_PATH,
                  SPEC_PATH, RENT_SPEC_PATH, GEO_SPEC_PATH, ALIAS_PATH]
    for path in base_paths:
        require(path.is_file(), f"Missing {path.relative_to(ROOT)}. Finish the relevant existing pipeline first.")
    input_hashes = {path: fingerprint(path) for path in base_paths}
    transport_report = read_json(REPORT_PATH)
    geo_report = read_json(GEO_REPORT_PATH)
    rent_report = read_json(RENT_REPORT_PATH)
    spec = read_json(SPEC_PATH)
    rent_spec = load_snapshot(RENT_SPEC_PATH)
    geo_spec = read_json(GEO_SPEC_PATH)
    require(transport_report.get("builder") == "scripts/build_transport.py" and transport_report.get("check_only") is False,
            "A completed transport build report is required.")
    for flag in ["counts_reconciled", "csv_readback_matches", "gpkg_readback_matches", "upstream_inputs_unchanged"]:
        require(transport_report.get(flag) is True, f"Transport report is incomplete: {flag}.")
    require(transport_report.get("transport_snapshot") == spec, "Transport configuration differs from its report.")
    require(spec["service_date"] == SERVICE_DATE and spec["timezone"] == TIMEZONE,
            "This notebook is reviewed for 2026-10-13 in Melbourne service-day time.")
    require(spec["category_feed"] == CATEGORY_FEED and spec["windows"][AM_WINDOW] == [25200, 32400],
            "Reviewed categories or morning window changed.")
    require(spec["rental_reporting_quarter"] == RENT_QUARTER and spec["lga_count"] == 31,
            "Reviewed rental period or study area changed.")
    require(geo_report.get("boundary_snapshot") == geo_spec and geo_report.get("check_only") is False,
            "A compatible completed geography build is required.")
    require(geo_spec["map_quarter"] == RENT_QUARTER and geo_spec["boundary_year"] == 2025,
            "Geography/rental snapshot mismatch.")
    require(rent_report.get("source", {}).get("sha256") == rent_spec["sha256"], "Rental source snapshot mismatch.")
    require(rent_report.get("output_sha256", {}).get(RENT_PATH.name) == fingerprint(RENT_PATH),
            "Rental CSV differs from its own quality report.")
    geo_hashes = {k.replace("\\", "/"): v for k, v in geo_report["output_sha256"].items()}
    require(geo_hashes.get(CROSSWALK_PATH.relative_to(ROOT).as_posix()) == fingerprint(CROSSWALK_PATH),
            "Crosswalk differs from the geography build report.")
    # Native 2025 geometry is not needed for charting but its fingerprint links the geographic builds.
    native_path = ROOT / "data/processed/geography/metro_lga_2025.gpkg"
    require(native_path.is_file(), "Missing previously validated LGA geometry.")
    input_hashes[native_path] = fingerprint(native_path)
    transport_inputs = {k.replace("\\", "/"): v for k, v in transport_report["input_sha256"].items()}
    for path in [CROSSWALK_PATH, native_path]:
        require(transport_inputs.get(path.relative_to(ROOT).as_posix()) == fingerprint(path),
                f"Transport was built from different geography: {path.name}.")
    for filename, expected_hash in [("data/raw/transport/gtfs.zip", spec["sha256"]),
                                    ("data/raw/geography/" + geo_spec["filename"], geo_spec["sha256"])]:
        require(transport_inputs.get(filename) == expected_hash, "Recorded source lineage differs.")


    def load_transport_csv(relative):
        path = TRANSPORT / relative
        require(path.is_file(), f"Missing processed transport output: {relative}")
        digest = fingerprint(path)
        hashes = {k.replace("\\", "/"): v for k, v in transport_report["output_sha256"].items()}
        require(hashes.get(relative) == digest, f"{relative}: fingerprint differs from its completed pipeline report.")
        frame = pd.read_csv(path, dtype="string", keep_default_na=False)
        schema = transport_report["output_schemas"].get(relative, {})
        require(schema.get("rows") == len(frame) and schema.get("columns") == frame.columns.tolist(),
                f"{relative}: recorded schema differs.")
        input_hashes[path] = digest
        return frame


    lga_service = count_columns(load_transport_csv("service/lga_service_indicators.csv"),
                                COUNT_FIELDS + ["eligible_events_excluding_near_boundary"], "LGA service")
    stop_service = count_columns(load_transport_csv("service/stop_service_indicators.csv"),
                                 ["eligible_departure_events", "unique_trip_records", "unique_route_records",
                                  "first_departure_seconds", "last_departure_seconds"], "stop service")
    memberships = load_transport_csv("service/trip_lga_memberships.csv")
    network_service = count_columns(load_transport_csv("service/feed_service_summary.csv"), COUNT_FIELDS, "study area")
    locations = load_transport_csv("spatial/stop_lga_matches.csv")
    crosswalk = pd.read_csv(CROSSWALK_PATH, dtype="string", keep_default_na=False)
    panel = read_panel_csv(RENT_PATH)
    require(panel.columns.tolist() == COLUMN_ORDER, "Rental 14-column contract changed.")
    require_key(panel, KEY_COLUMNS, "rental panel")
    require(len(panel) == spec["lga_count"] * len(pd.period_range(rent_spec["first_quarter"], rent_spec["last_quarter"], freq="Q")) and len(crosswalk) == spec["lga_count"], "Unexpected input scope.")
    require_key(crosswalk, [CODE], "crosswalk codes")
    require_key(crosswalk, ["rental_area_name"], "crosswalk names")
    require(crosswalk["boundary_year"].eq("2025").all(), "Crosswalk boundary year changed.")

    return {"lga_service": lga_service, "stop_service": stop_service, "memberships": memberships,
            "network_service": network_service, "locations": locations, "crosswalk": crosswalk,
            "panel": panel, "spec": spec, "rent_spec": rent_spec, "geo_spec": geo_spec,
            "native_path": native_path, "input_hashes": input_hashes}


def derive_tables(inputs: dict[str, Any]) -> dict[str, pd.DataFrame]:
    lga_service = inputs["lga_service"].copy(deep=True)
    stop_service = inputs["stop_service"].copy(deep=True)
    memberships = inputs["memberships"].copy(deep=True)
    network_service = inputs["network_service"].copy(deep=True)
    locations = inputs["locations"].copy(deep=True)
    crosswalk = inputs["crosswalk"].copy(deep=True)
    panel = inputs["panel"].copy(deep=True)
    spec, rent_spec, geo_spec = (inputs[name] for name in ("spec", "rent_spec", "geo_spec"))
    require(panel.columns.tolist() == COLUMN_ORDER, "Rental schema changed.")
    require_key(panel, KEY_COLUMNS, "rental panel")
    require_key(crosswalk, [CODE], "crosswalk")
    require_key(crosswalk, ["rental_area_name"], "crosswalk names")
    require_key(lga_service, GROUP, "LGA service grid")
    require_key(stop_service, GROUP + ["stop_key"], "stop/category grid")
    require_key(memberships, GROUP + ["trip_key"], "trip memberships")
    require_key(network_service, ["feed_id", "service_category", "window"], "study-area summary")
    require_key(locations, ["feed_id", "stop_id"], "stored locations")
    require_key(locations, ["stop_key"], "stored stop keys")
    require(locations.stop_key.eq(locations.feed_id + ":" + locations.stop_id).all(), "Location namespace changed.")
    known_codes = set(crosswalk[CODE])
    for label, frame in [("LGA", lga_service), ("stop", stop_service), ("membership", memberships), ("study area", network_service)]:
        require(frame.service_date.eq(SERVICE_DATE).all() and frame.agency_timezone.eq(TIMEZONE).all(), f"{label}: mixed dates/timezones.")
        require(frame.window.isin([AM_WINDOW, DAY_WINDOW]).all(), f"{label}: unexpected window.")
        require(frame.service_category.isin(CATEGORY_FEED).all(), f"{label}: unknown category.")
        require(frame.feed_id.eq(frame.service_category.map(CATEGORY_FEED)).all(), f"{label}: category/feed mismatch.")
        if CODE in frame:
            require(set(frame[CODE]).issubset(known_codes), f"{label}: unreviewed LGA code.")
    expected_grid = {(c, f, cat, w) for c in known_codes for cat, f in CATEGORY_FEED.items()
                     for w in [AM_WINDOW, DAY_WINDOW]}
    require(set(lga_service[GROUP].itertuples(index=False, name=None)) == expected_grid and len(lga_service) == len(known_codes) * len(CATEGORY_FEED) * 2,
            "Incomplete LGA/category/window grid. Missing rows are not assumed to be zero.")
    identity = lga_service[[CODE, "abs_lga_name", "rental_area_name"]].drop_duplicates()
    require_key(identity, [CODE], "service LGA identity")
    pd.testing.assert_frame_equal(identity.sort_values(CODE).reset_index(drop=True),
                                  crosswalk[[CODE, "abs_lga_name", "rental_area_name"]].sort_values(CODE).reset_index(drop=True),
                                  check_dtype=False, check_exact=True)
    require(memberships.groupby("trip_key")[["feed_id", "service_category", "route_key"]].nunique().eq(1).all().all(),
            "One trip belongs to conflicting feeds/categories/routes.")
    require(memberships.trip_key.str.split(":", n=1).str[0].eq(memberships.feed_id).all(), "Trip namespace lost.")
    require(stop_service.stop_key.eq(stop_service.feed_id + ":" + stop_service.stop_id).all(), "Service-stop namespace lost.")
    assigned = locations.loc[locations.spatial_match_status.eq("matched_within"),
                             ["feed_id", "stop_id", "stop_key", "stop_name", CODE]].copy()
    require(len(assigned) == spec["spatial_counts"]["matched_within"] and set(assigned[CODE]).issubset(known_codes), "Assigned stop inventory changed.")
    stop_pairs = stop_service[["stop_key", CODE]].drop_duplicates()
    require_key(stop_pairs, ["stop_key"], "service stop assignments")
    assignment_check = stop_pairs.merge(assigned[["stop_key", CODE]], on="stop_key", how="left",
                                       suffixes=("_service", "_location"), validate="one_to_one", indicator=True)
    require(assignment_check["_merge"].eq("both").all()
            and assignment_check[f"{CODE}_service"].eq(assignment_check[f"{CODE}_location"]).all(),
            "A served stop is missing or assigned to the wrong LGA.")
    ref = lga_service.set_index(GROUP).sort_index()
    for field, actual in [
        ("eligible_departure_events", stop_service.groupby(GROUP).eligible_departure_events.sum()),
        ("served_stop_records", stop_service.groupby(GROUP).stop_key.nunique()),
        ("unique_trip_records", memberships.groupby(GROUP).trip_key.nunique()),
        ("unique_route_records", memberships.groupby(GROUP).route_key.nunique()),
    ]:
        require(np.array_equal(actual.reindex(ref.index, fill_value=0).to_numpy(), ref[field].to_numpy()),
                f"Independent LGA count mismatch: {field}.")
    net_keys = ["feed_id", "service_category", "window"]
    net_ref = network_service.set_index(net_keys).sort_index()
    for field, actual in [
        ("eligible_departure_events", lga_service.groupby(net_keys).eligible_departure_events.sum()),
        ("unique_trip_records", memberships.groupby(net_keys).trip_key.nunique()),
        ("unique_route_records", memberships.groupby(net_keys).route_key.nunique()),
        ("served_stop_records", stop_service.groupby(net_keys).stop_key.nunique()),
    ]:
        require(np.array_equal(actual.reindex(net_ref.index, fill_value=0).to_numpy(), net_ref[field].to_numpy()),
                f"Independent study-area mismatch: {field}.")
    require(lga_service.eligible_events_excluding_near_boundary.eq(
        lga_service.eligible_departure_events - lga_service.near_boundary_events).all(), "Near-boundary subtraction mismatch.")
    for column in COUNT_FIELDS[1:]:
        require(lga_service[column].le(lga_service.eligible_departure_events).all(), f"Impossible {column} count.")
    day = lga_service.loc[lga_service.window.eq(DAY_WINDOW)].set_index([CODE, "service_category"]).sort_index()
    am = lga_service.loc[lga_service.window.eq(AM_WINDOW)].set_index([CODE, "service_category"]).sort_index()
    require(am[COUNT_FIELDS].le(day[COUNT_FIELDS]).all().all() and am.extended_time_events.eq(0).all(),
            "AM window is not a valid subset of the service day.")
    AM_EVENTS = int(am.eligible_departure_events.sum())
    AM_UNIQUE_TRIPS = int(memberships.loc[memberships.window.eq(AM_WINDOW), "trip_key"].nunique())
    require(AM_EVENTS == spec["expected_totals"]["am_events"] and AM_UNIQUE_TRIPS == spec["expected_totals"]["am_trips"], "Audited morning totals changed.")
    am_totals = aggregate_lgas(lga_service, memberships, stop_service, known_codes, AM_WINDOW)
    day_totals = aggregate_lgas(lga_service, memberships, stop_service, known_codes, DAY_WINDOW)
    am_totals = am_totals.rename(columns={c: "am_" + c for c in am_totals if c != CODE})
    day_totals = day_totals.rename(columns={c: "service_day_" + c for c in day_totals if c != CODE})
    transport_comparison = complete_one_to_one(crosswalk[[CODE, "abs_lga_name", "rental_area_name", "source_region"]],
                                             am_totals, CODE, "AM totals")
    transport_comparison = complete_one_to_one(transport_comparison, day_totals, CODE, "service-day totals")
    transport_comparison["transport_service_date"] = SERVICE_DATE
    transport_comparison["transport_timezone"] = TIMEZONE
    transport_comparison["am_window"] = "07:00 inclusive to 09:00 exclusive"
    transport_comparison["am_events_per_counted_trip"] = safe_ratio(
        transport_comparison.am_departure_events, transport_comparison.am_unique_trip_records)
    transport_comparison["am_share_of_service_day_events_pct"] = 100 * safe_ratio(
        transport_comparison.am_departure_events, transport_comparison.service_day_departure_events)
    transport_comparison["am_near_boundary_event_share_pct"] = 100 * safe_ratio(
        transport_comparison.am_near_boundary_events, transport_comparison.am_departure_events)
    require(len(transport_comparison) == spec["lga_count"], "Expected one transport row per LGA.")


    am_stops = stop_service.loc[stop_service.window.eq(AM_WINDOW)]
    am_stop_totals = am_stops.groupby([CODE, "stop_key"], as_index=False).eligible_departure_events.sum()
    require_key(am_stop_totals, ["stop_key"], "AM counted stops")
    stop_context = assigned.merge(am_stop_totals, on=[CODE, "stop_key"], how="left", validate="one_to_one", indicator=True)
    # Earlier checks proved that all counted stops occur in the assigned inventory.
    stop_context["am_events"] = stop_context.eligible_departure_events.fillna(0).astype("int64")
    require(stop_context.loc[stop_context["_merge"].eq("both"), "am_events"].gt(0).all(), "A served stop has zero events.")
    require(int(stop_context.am_events.sum()) == AM_EVENTS, "Stop-level denominator context lost events.")
    stop_context = stop_context.drop(columns=["eligible_departure_events", "_merge"])
    profile = stop_context.groupby(CODE).agg(
        assigned_stop_records=("stop_key", "size"),
        am_served_stop_records_check=("am_events", lambda s: int(s.gt(0).sum())),
        am_events_check=("am_events", "sum"),
        am_median_events_per_assigned_stop_record=("am_events", "median"),
    ).reindex(sorted(known_codes))
    require(profile["assigned_stop_records"].notna().all(), "An LGA has no assignment inventory; investigate before assigning rates.")
    for col in ["assigned_stop_records", "am_served_stop_records_check", "am_events_check"]:
        profile[col] = profile[col].astype("int64")
    profile["assigned_records_without_counted_am_event"] = profile.assigned_stop_records - profile.am_served_stop_records_check
    profile["mean_am_events_per_assigned_stop_record"] = safe_ratio(profile.am_events_check, profile.assigned_stop_records)
    profile["mean_am_events_per_served_stop_record"] = safe_ratio(profile.am_events_check, profile.am_served_stop_records_check)
    profile["assigned_record_share_with_counted_am_event_pct"] = 100 * safe_ratio(
        profile.am_served_stop_records_check, profile.assigned_stop_records)
    denominator_comparison = complete_one_to_one(crosswalk[[CODE, "rental_area_name"]], profile.reset_index(), CODE, "denominator profile")
    transport_comparison = complete_one_to_one(transport_comparison,
        profile.drop(columns=["am_served_stop_records_check", "am_events_check"]).reset_index(), CODE, "transport denominators")
    check = transport_comparison.set_index(CODE).sort_index()
    require(np.array_equal(check.am_departure_events, profile.am_events_check), "LGA denominator event totals disagree.")
    require(np.array_equal(check.am_served_stop_records, profile.am_served_stop_records_check), "LGA served-record counts disagree.")


    expected_quarters = pd.period_range(rent_spec["first_quarter"], rent_spec["last_quarter"], freq="Q").astype(str).tolist()
    for _, group in panel.groupby(["rental_area_name", "property_type"], sort=False):
        require(group.sort_values("quarter_end").quarter.tolist() == expected_quarters, "Rental quarter coverage changed.")
    actual_dates = pd.DatetimeIndex(panel.quarter_end).as_unit("ns")
    expected_dates = pd.PeriodIndex(panel.quarter, freq="Q").to_timestamp(how="end").normalize().as_unit("ns")
    require(np.array_equal(actual_dates.asi8, expected_dates.asi8), "Rental dates and quarters disagree.")
    latest = panel.loc[panel.quarter.eq(RENT_QUARTER)].copy().reset_index(drop=True)
    require(len(latest) == spec["lga_count"] and latest.property_type.eq("2 bedroom flats").all(), "Unexpected rental period/category.")
    require_key(latest, ["rental_area_name"], "latest rent")
    require(latest.set_index("rental_area_name").source_region.to_dict()
            == crosswalk.set_index("rental_area_name").source_region.to_dict(), "Rental source groups differ from the crosswalk.")
    latest_coded = complete_one_to_one(latest, crosswalk.drop(columns="source_region"), "rental_area_name", "rental code attachment")
    transport_for_join = transport_comparison.drop(columns=["abs_lga_name", "rental_area_name", "source_region"])
    combined = complete_one_to_one(latest_coded, transport_for_join, CODE, "rental/transport merge")
    combined = combined.sort_values("rental_area_name", kind="stable").reset_index(drop=True)
    require(len(combined) == spec["lga_count"] and combined[CODE].is_unique, "Joined table lost or multiplied LGAs.")
    pd.testing.assert_frame_equal(combined[COLUMN_ORDER].sort_values(KEY_COLUMNS).reset_index(drop=True),
                                  latest[COLUMN_ORDER].sort_values(KEY_COLUMNS).reset_index(drop=True), check_exact=True)
    require(combined.quarter.eq(RENT_QUARTER).all() and combined.transport_service_date.eq(SERVICE_DATE).all(),
            "Source periods must remain separate.")


    transport_comparison = transport_comparison.sort_values("rental_area_name", kind="stable").reset_index(drop=True)
    am_categories = lga_service.loc[lga_service.window.eq(AM_WINDOW)].copy()
    am_categories["service_category_label"] = am_categories.service_category.map(CATEGORY_LABELS)
    source_periods = pd.DataFrame([
        {"component": "rent", "period": RENT_QUARTER, "scope": "2 bedroom flats; 31 source-group metropolitan LGAs",
         "source_file": rent_spec["filename"], "source_sha256": rent_spec["sha256"], "publisher_page": rent_spec["publisher_page"]},
        {"component": "boundaries", "period": "2025", "scope": "ABS statistical LGA boundaries; reviewed code/name crosswalk",
         "source_file": geo_spec["filename"], "source_sha256": geo_spec["sha256"], "publisher_page": geo_spec.get("publisher_page", "https://www.abs.gov.au/")},
        {"component": "transport", "period": SERVICE_DATE, "scope": "Feeds 2,3,4; Melbourne service day; AM 07:00 inclusive–09:00 exclusive",
         "source_file": spec["filename"], "source_sha256": spec["sha256"], "publisher_page": spec["publisher_page"]},
    ])
    reconciliation_rows = []
    for w in [DAY_WINDOW, AM_WINDOW]:
        frame = memberships.loc[memberships.window.eq(w)]
        events = int(lga_service.loc[lga_service.window.eq(w), "eligible_departure_events"].sum())
        reconciliation_rows.append({"window": w, "service_date": SERVICE_DATE, "agency_timezone": TIMEZONE,
            "eligible_departure_events": events, "distinct_study_area_trips": int(frame.trip_key.nunique()),
            "sum_of_lga_trip_counts_not_a_study_area_total": int(frame.groupby(CODE).trip_key.nunique().sum()),
            "distinct_study_area_served_stop_records": int(stop_service.loc[stop_service.window.eq(w), "stop_key"].nunique())})
    reconciliation = pd.DataFrame(reconciliation_rows)
    TABLES = {
        "am_lga_category_comparison.csv": am_categories.sort_values([CODE, "service_category"]).reset_index(drop=True),
        "lga_transport_comparison.csv": transport_comparison,
        "rent_transport_comparison.csv": combined,
        "am_stop_denominator_comparison.csv": denominator_comparison.sort_values(CODE).reset_index(drop=True),
        "study_area_reconciliation.csv": reconciliation,
        "source_periods.csv": source_periods,
    }
    history = attach_history_codes(panel, crosswalk)
    TABLES["rental_history.csv"] = history
    TABLES["lga_service_categories.csv"] = lga_service.sort_values(GROUP, kind="stable").reset_index(drop=True)
    return TABLES
