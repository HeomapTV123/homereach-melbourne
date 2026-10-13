"""Pure stop preparation and strict spatial assignment from notebook 06."""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
import geopandas as gpd
import pyproj
import shapely
from .gtfs import require

STOP_KEYS = ["feed_id", "stop_id"]
STATUS_ORDER = ["matched_within", "outside_selected_lgas", "boundary_review", "ambiguous_review", "invalid_coordinates"]
CODE = "lga_code_2025"
NAME = "abs_lga_name"

def validate_areas(areas):
    require(isinstance(areas, gpd.GeoDataFrame) and areas.crs is not None, "LGA polygons need a CRS.")
    require({CODE, NAME, "geometry"}.issubset(areas.columns), "Missing LGA columns.")
    require(areas[CODE].notna().all() and areas[CODE].is_unique, "Duplicate or missing LGA code.")
    require(areas[NAME].notna().all(), "Missing LGA name.")
    require(not areas.geometry.is_empty.any() and areas.geometry.notna().all(), "Missing or empty LGA geometry.")
    require(areas.geometry.is_valid.all(), "Invalid LGA polygon; do not repair silently.")
    require(areas.geom_type.isin(["Polygon", "MultiPolygon"]).all(), "Non-polygon LGA feature.")

def prepare_locations(feed_tables, labels):
    """Preserve every original stops.txt field as text. Add separate derived columns."""
    parts = []
    required = {"stop_id", "stop_name", "stop_lat", "stop_lon", "location_type", "parent_station", "wheelchair_boarding"}
    reserved = {"feed_id", "stop_key", "parent_key", "operational_group", "source_member", "source_record_number", "location_type_effective", "coordinate_valid", "latitude", "longitude", "parent_stop_name", "parent_wheelchair_boarding"}
    for fid, original in feed_tables.items():
        require(required.issubset(original.columns), f"Feed {fid}: expected stops.txt fields are absent.")
        require(not reserved.intersection(original.columns), "Source fields collide with derived fields.")
        frame = original.copy(deep=True)
        require(frame.notna().all().all(), "Use keep_default_na=False when reading original GTFS text.")
        require(frame.stop_id.ne("").all() and frame.stop_id.eq(frame.stop_id.str.strip()).all(), "Blank or padded stop ID.")
        require(frame.stop_id.is_unique, f"Feed {fid}: duplicate stop ID.")
        lt = frame.location_type.replace("", "0")
        require(lt.isin(["0", "1", "2", "3", "4"]).all(), "Invalid location_type.")
        require(frame.parent_station.isin(set(frame.stop_id) | {""}).all(), "Unresolved parent in the same feed.")
        lookup = frame.assign(_location_type=lt).set_index("stop_id")
        children = lt.eq("0") & frame.parent_station.ne("")
        require(frame.loc[children, "parent_station"].map(lookup._location_type).eq("1").all(), "A platform parent is not a station.")
        frame["feed_id"] = fid
        frame["operational_group"] = labels[fid]
        frame["source_member"] = f"{fid}/google_transit.zip!stops.txt"
        frame["source_record_number"] = np.arange(1, len(frame) + 1, dtype=np.int64)
        frame["stop_key"] = fid + ":" + frame.stop_id
        frame["parent_key"] = (fid + ":" + frame.parent_station).where(frame.parent_station.ne(""), "")
        frame["parent_stop_name"] = frame.parent_station.map(lookup.stop_name).fillna("")
        frame["parent_wheelchair_boarding"] = frame.parent_station.map(lookup.wheelchair_boarding).fillna("")
        frame["location_type_effective"] = lt
        frame["latitude"] = pd.to_numeric(frame.stop_lat, errors="coerce").astype("float64")
        frame["longitude"] = pd.to_numeric(frame.stop_lon, errors="coerce").astype("float64")
        frame["coordinate_valid"] = (
            np.isfinite(frame.latitude) & np.isfinite(frame.longitude)
            & frame.latitude.between(-90, 90) & frame.longitude.between(-180, 180)
        )
        parts.append(frame)
    # Optional columns absent in a feed become empty strings. The original per-feed schemas are recorded separately.
    locations = pd.concat(parts, ignore_index=True, sort=False)
    numeric = {"source_record_number", "latitude", "longitude", "coordinate_valid"}
    for col in locations.columns.difference(list(numeric)):
        locations[col] = locations[col].astype("string").fillna("")
    require(not locations.duplicated(STOP_KEYS).any() and locations.stop_key.is_unique, "Combined stop key is not unique.")
    selected = locations.loc[locations.location_type_effective.eq("0")].copy().reset_index(drop=True)
    excluded = locations.loc[~locations.location_type_effective.eq("0")].copy().reset_index(drop=True)
    reasons = {"1": "parent_station_not_platform", "2": "entrance_exit_not_platform", "3": "generic_node_not_platform", "4": "boarding_area_not_platform"}
    excluded["exclusion_reason"] = excluded.location_type_effective.map(reasons).astype("string")
    return locations, selected, excluded

def assign_points(points, areas):
    """Strict interior-only assignment; retain all points and all polygon candidates."""
    validate_areas(areas)
    require(isinstance(points, gpd.GeoDataFrame) and points.crs == areas.crs, "Point and polygon CRS must agree.")
    require(points.stop_key.notna().all() and points.stop_key.is_unique, "Duplicate or missing stop_key.")
    require(not points.duplicated(STOP_KEYS).any(), "Duplicate feed_id/stop_id pair.")
    require(points.loc[points.geometry.notna()].geom_type.eq("Point").all(), "Expected point geometry only.")
    result = points.copy(deep=True).reset_index(drop=True)
    result["_point_row"] = np.arange(len(result), dtype=np.int64)
    valid = result.loc[result.geometry.notna() & ~result.geometry.is_empty & result.geometry.is_valid]
    # An intersecting point may be in an interior or exactly on a boundary.
    joined = gpd.sjoin(valid[["_point_row", "stop_key", "geometry"]],
                       areas[[CODE, NAME, "geometry"]].reset_index(drop=True),
                       how="inner", predicate="intersects")
    if len(joined):
        right_geom = areas.reset_index(drop=True).geometry.iloc[joined.index_right.astype(int)].to_numpy()
        interior = shapely.within(joined.geometry.to_numpy(), right_geom)
        pairs = pd.DataFrame(joined[["_point_row", "stop_key", CODE, NAME]]).copy()
        pairs["relation"] = np.where(interior, "within", "boundary")
        pairs = pairs.sort_values(["stop_key", CODE], kind="stable").reset_index(drop=True)
    else:
        pairs = pd.DataFrame(columns=["_point_row", "stop_key", CODE, NAME, "relation"])
    require(not pairs.duplicated(["stop_key", CODE]).any(), "Duplicate point/polygon candidate.")
    n_candidates = pairs.groupby("_point_row").size()
    n_inside = pairs.loc[pairs.relation.eq("within")].groupby("_point_row").size()
    result["candidate_count"] = result._point_row.map(n_candidates).fillna(0).astype("int64")
    result["interior_count"] = result._point_row.map(n_inside).fillna(0).astype("int64")
    valid_mask = result.geometry.notna() & ~result.geometry.is_empty & result.geometry.is_valid
    status = pd.Series("invalid_coordinates", index=result.index, dtype="string")
    status.loc[valid_mask & result.candidate_count.eq(0)] = "outside_selected_lgas"
    status.loc[valid_mask & result.candidate_count.eq(1) & result.interior_count.eq(0)] = "boundary_review"
    status.loc[valid_mask & result.candidate_count.gt(1)] = "ambiguous_review"
    assigned = valid_mask & result.candidate_count.eq(1) & result.interior_count.eq(1)
    status.loc[assigned] = "matched_within"
    result["spatial_match_status"] = status
    result[CODE] = pd.Series(pd.NA, index=result.index, dtype="string")
    result[NAME] = pd.Series(pd.NA, index=result.index, dtype="string")
    single_rows = result.loc[assigned, "_point_row"]
    single = pairs.loc[pairs._point_row.isin(single_rows)].set_index("_point_row")
    result.loc[assigned, CODE] = result.loc[assigned, "_point_row"].map(single[CODE]).astype("string").to_numpy()
    result.loc[assigned, NAME] = result.loc[assigned, "_point_row"].map(single[NAME]).astype("string").to_numpy()
    codes = pairs.groupby("_point_row")[CODE].agg(lambda x: json.dumps(sorted(x.astype(str)), separators=(",", ":")))
    result["candidate_lga_codes_json"] = result._point_row.map(codes).fillna("[]").astype("string")
    # Audit all candidate associations, not just selected assignments.
    candidate_table = pairs.drop(columns="_point_row").merge(
        pd.DataFrame(result[["stop_key", *STOP_KEYS]]), on="stop_key", how="left", validate="many_to_one")
    candidate_table = candidate_table[["stop_key", *STOP_KEYS, CODE, NAME, "relation"]]
    result = result.drop(columns="_point_row")
    require(len(result) == len(points) and result.stop_key.is_unique, "Spatial join lost or duplicated source rows.")
    require(result[CODE].notna().eq(result.spatial_match_status.eq("matched_within")).all(), "Unreviewed assignment.")
    return result, candidate_table

def mark_near_boundaries(points, areas, radius_m=10.0):
    """Diagnostic flag only: never snap, buffer-assign or change an LGA code."""
    require(points.crs == areas.crs and points.crs.is_projected, "Boundary distance needs the same projected CRS.")
    require(all(a.unit_name == "metre" for a in points.crs.axis_info[:2]), "Projected coordinates must be metres.")
    require(np.isfinite(radius_m) and radius_m > 0, "Positive finite diagnostic radius required.")
    edges = gpd.GeoDataFrame(areas[[CODE]].copy(), geometry=areas.geometry.boundary, crs=areas.crs).reset_index(drop=True)
    valid = points.loc[points.geometry.notna() & ~points.geometry.is_empty]
    near = gpd.sjoin(valid[["stop_key", "geometry"]], edges, how="inner", predicate="dwithin", distance=radius_m)
    return points.stop_key.isin(set(near.stop_key))

def verify_assignments(result, points, areas):
    """Independent per-point checks against all 31 polygons, not another spatial join."""
    require(result.stop_key.tolist() == points.stop_key.tolist(), "Source order/key changed.")
    require(result.spatial_match_status.isin(STATUS_ORDER).all(), "Unknown match status.")
    lookup = areas.set_index(CODE)
    n = 0
    polygons = areas.geometry.to_numpy()
    all_codes = areas[CODE].astype(str).to_numpy()
    for row in result.itertuples(index=False):
        point = row.geometry
        if point is None or point.is_empty or not point.is_valid:
            require(row.spatial_match_status == "invalid_coordinates", "Invalid point received an assignment.")
            continue
        hit = shapely.intersects(polygons, point)
        codes = sorted(all_codes[hit].tolist())
        interiors = int(shapely.contains(polygons, point).sum())
        require(json.loads(row.candidate_lga_codes_json) == codes, "Candidate codes do not match polygon relationships.")
        require(row.candidate_count == len(codes) and row.interior_count == interiors, "Candidate counts disagree.")
        if len(codes) == 1 and interiors == 1:
            require(row.spatial_match_status == "matched_within" and getattr(row, CODE) == codes[0], "Incorrect assigned LGA.")
            require(getattr(row, NAME) == lookup.loc[codes[0], NAME], "Assigned code/name mismatch.")
        elif len(codes) > 1:
            require(row.spatial_match_status == "ambiguous_review" and pd.isna(getattr(row, CODE)), "Ambiguous point forced into an LGA.")
        elif len(codes) == 1:
            require(row.spatial_match_status == "boundary_review" and pd.isna(getattr(row, CODE)), "Boundary point forced into an LGA.")
        else:
            require(row.spatial_match_status == "outside_selected_lgas" and pd.isna(getattr(row, CODE)), "Outside point forced into an LGA.")
        n += 1
    # Geometry copies must remain unchanged throughout the matching routine.
    require(all((a is None and b is None) or (a is not None and b is not None and a.equals_exact(b, 0.0))
                for a, b in zip(result.geometry, points.geometry)), "Point coordinates changed during matching.")
    return n

def build_spatial(stop_tables: dict, native: gpd.GeoDataFrame, crosswalk: pd.DataFrame, spec: dict):
    """Rebuild every notebook-06 table without writing or modifying any input."""
    SELECTED_FEEDS = tuple(spec["feed_ids"])
    FEED_LABELS = spec["feed_labels"]
    EXPECTED_LOCATIONS = spec["location_counts"]
    EXPECTED_PLATFORMS = spec["platform_counts"]
    POINT_EPSG, MATCH_EPSG = spec["point_epsg"], spec["match_epsg"]
    BOUNDARY_REVIEW_METRES = spec["near_boundary_metres"]
    EXPECTED_GTFS_SHA256 = spec["sha256"]
    locations, stops, excluded_locations = prepare_locations(stop_tables, FEED_LABELS)
    for fid in SELECTED_FEEDS:
        require(int(stops.feed_id.eq(fid).sum()) == EXPECTED_PLATFORMS[fid], f'Unexpected platform selection for feed {fid}.')
    require(len(locations) == 27115 and len(stops) == 25031 and (len(excluded_locations) == 2084), 'Location accounting differs from the audit.')
    require(len(stops) + len(excluded_locations) == len(locations), 'A source location was lost.')
    for fid, original in stop_tables.items():
        preserved = locations.loc[locations.feed_id.eq(fid), original.columns].reset_index(drop=True)
        pd.testing.assert_frame_equal(preserved, original.reset_index(drop=True), check_exact=True)
    require(stops.coordinate_valid.all(), 'A reviewed platform now has invalid coordinates. Stop and investigate the changed input.')
    location_inventory = pd.DataFrame([{'feed_id': fid, 'operational_group': FEED_LABELS[fid], 'all_location_records': EXPECTED_LOCATIONS[fid], 'selected_stop_platform_records': int(stops.feed_id.eq(fid).sum()), 'excluded_non_platform_records': int(excluded_locations.feed_id.eq(fid).sum())} for fid in SELECTED_FEEDS])
    shared_raw_stop_ids = int(stops.groupby('stop_id').feed_id.nunique().gt(1).sum())
    require(shared_raw_stop_ids == 41, 'Cross-feed stop-ID inventory differs from the reviewed source.')
    source_points = gpd.GeoDataFrame(stops.copy(), geometry=gpd.points_from_xy(stops.longitude, stops.latitude), crs=POINT_EPSG)
    working_points = source_points.to_crs(MATCH_EPSG)
    working_areas = native[[CODE, NAME, 'geometry']].to_crs(MATCH_EPSG).reset_index(drop=True)
    validate_areas(working_areas)
    require(working_points.geometry.is_valid.all() and (not working_points.geometry.is_empty.any()), 'Invalid transformed point.')
    transformer = pyproj.Transformer.from_crs(POINT_EPSG, MATCH_EPSG, always_xy=True)
    transformer.transform(float(stops.longitude.iloc[0]), float(stops.latitude.iloc[0]), errcheck=True)
    try:
        used_operation = transformer.get_last_used_operation()
    except (AttributeError, pyproj.exceptions.ProjError):
        used_operation = transformer
    crs_record = {'source_points': 'EPSG:4326', 'source_polygons': 'EPSG:7844', 'working': 'EPSG:7855', 'operation_description': used_operation.description, 'operation_definition': used_operation.definition, 'reported_operation_accuracy_m': used_operation.accuracy, 'caution': 'Operation metadata does not quantify source-coordinate or boundary accuracy. No coordinate epoch was supplied.'}
    matched_working, spatial_candidates = assign_points(working_points, working_areas)
    independent_checks = verify_assignments(matched_working, working_points, working_areas)
    require(independent_checks == len(stops), 'Some valid locations were not independently checked.')
    require(matched_working[STOP_KEYS].equals(stops[STOP_KEYS]), 'Composite source keys changed.')
    matched_working['near_boundary_10m'] = mark_near_boundaries(working_points, working_areas, BOUNDARY_REVIEW_METRES).to_numpy()
    status_index = pd.MultiIndex.from_product([SELECTED_FEEDS, STATUS_ORDER], names=['feed_id', 'spatial_match_status'])
    status_summary = matched_working.groupby(['feed_id', 'spatial_match_status']).size().reindex(status_index, fill_value=0).rename('stop_records').reset_index()
    status_summary['operational_group'] = status_summary.feed_id.map(FEED_LABELS)
    require(status_summary.stop_records.sum() == len(stops), 'Status totals do not account for every stop.')
    new_columns = [CODE, NAME, 'candidate_count', 'interior_count', 'candidate_lga_codes_json', 'spatial_match_status', 'near_boundary_10m']
    for col in new_columns:
        require(col not in stops.columns, 'Derived column would overwrite a source field.')
    attributes = pd.DataFrame(matched_working.drop(columns='geometry')).copy()
    attributes['boundary_year'] = 2025
    attributes['gtfs_source_sha256'] = EXPECTED_GTFS_SHA256
    attributes['stop_coordinate_crs'] = 'EPSG:4326'
    attributes['spatial_match_crs'] = 'EPSG:7855'
    attributes[CODE] = attributes[CODE].astype('string').fillna('')
    attributes[NAME] = attributes[NAME].astype('string').fillna('')
    for col in attributes.columns:
        if col not in {'source_record_number', 'latitude', 'longitude', 'coordinate_valid', 'candidate_count', 'interior_count', 'near_boundary_10m', 'boundary_year'}:
            attributes[col] = attributes[col].astype('string').fillna('')
    pd.testing.assert_frame_equal(attributes[stops.columns], stops, check_exact=True)
    matched_points = gpd.GeoDataFrame(attributes, geometry=source_points.geometry.copy(), crs=POINT_EPSG)
    require(not attributes.duplicated(STOP_KEYS).any() and attributes.stop_key.is_unique, 'Duplicate final key.')
    require(attributes[CODE].ne('').eq(attributes.spatial_match_status.eq('matched_within')).all(), 'An unreviewed location received a code.')
    unassigned = attributes.loc[~attributes.spatial_match_status.eq('matched_within')].copy()
    near_boundary_review = attributes.loc[attributes.near_boundary_10m].copy()
    assigned_counts = attributes.loc[attributes.spatial_match_status.eq('matched_within')].groupby([CODE, 'feed_id']).size()
    all_combinations = pd.MultiIndex.from_product([sorted(native[CODE]), SELECTED_FEEDS], names=[CODE, 'feed_id'])
    lga_inventory = assigned_counts.reindex(all_combinations, fill_value=0).rename('stored_stop_platform_records').reset_index()
    lga_inventory = lga_inventory.merge(crosswalk[[CODE, NAME, 'rental_area_name']], on=CODE, how='left', validate='many_to_one')
    lga_inventory['operational_group'] = lga_inventory.feed_id.map(FEED_LABELS)
    require(len(lga_inventory) == 93 and lga_inventory.stored_stop_platform_records.sum() == len(attributes) - len(unassigned), 'LGA/feed totals do not reconcile.')
    require(attributes.spatial_match_status.value_counts().to_dict() == spec["spatial_counts"], "Spatial result differs from the audited snapshot.")
    require(len(near_boundary_review) == spec["near_boundary_count"], "Boundary diagnostic differs from the audited snapshot.")
    outputs = {
        "stop_lga_matches.csv": attributes,
        "location_selection_counts.csv": location_inventory,
        "excluded_location_records.csv": excluded_locations,
        "spatial_candidates.csv": spatial_candidates,
        "spatial_match_summary.csv": status_summary,
        "unassigned_stops.csv": unassigned,
        "near_boundary_review.csv": near_boundary_review,
        "stop_records_by_lga_and_feed.csv": lga_inventory,
    }
    return outputs, matched_points, {"independent_point_checks": independent_checks, "crs": crs_record}

