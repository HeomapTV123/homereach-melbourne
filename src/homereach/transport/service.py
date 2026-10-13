"""Fixed-stop event selection and reconciled service summaries from notebook 07.

Complete trips are processed BEFORE geographic/time/pickup selection. Retained
rows for only one active feed are materialised; the full archive is not loaded.
"""
from __future__ import annotations
from pathlib import Path
from datetime import date
from time import perf_counter
from contextlib import contextmanager
import numpy as np
import pandas as pd
from .gtfs import require, require_key, open_feed

STOP_KEYS = ["feed_id", "stop_id"]
STOP_COLUMNS = [*STOP_KEYS, "stop_key", "stop_name", "lga_code_2025", "abs_lga_name", "spatial_match_status", "near_boundary_10m"]
WINDOWS = {"service_day": (None, None), "am_peak_0700_0900": (25200, 32400)}
CATEGORY_FEED = {"train_not_labelled_replacement": "2", "labelled_replacement_bus": "2", "tram": "3", "myki_bus": "4"}
RAW_EVENT_COLUMNS = ["trip_id", "stop_id", "stop_sequence", "arrival_time", "departure_time", "pickup_type", "drop_off_type"]
EVENT_KEYS = ["feed_id", "trip_id", "stop_sequence"]
OUTCOMES = ["terminal_trip_record", "no_pickup", "arrangement_required", "unassigned_location", "counted_regular_pickup"]
COUNT_FIELDS = ["eligible_departure_events", "unique_trip_records", "served_stop_records", "unique_route_records", "near_boundary_events", "extended_time_events"]
LGA_GROUP = ["lga_code_2025", "feed_id", "service_category", "window"]

def seconds_from_gtfs(values: pd.Series) -> pd.Series:
    """Parse the supplied times; do not convert 25:00 to 01:00."""
    text = values.astype("string")
    unique = pd.Series(text.unique(), dtype="string")
    require(unique.notna().all() and unique.str.fullmatch(r"[0-9]{1,2}:[0-5][0-9]:[0-5][0-9]").all(),
            "Blank or invalid GTFS time; do not fill/interpolate it.")
    split = unique.str.split(":", expand=True).astype("int64")
    seconds = split[0] * 3600 + split[1] * 60 + split[2]
    return text.map(dict(zip(unique, seconds))).astype("int64")

def in_window(events: pd.DataFrame, window: str) -> pd.Series:
    require(window in WINDOWS, f"Unknown time window: {window}")
    start, end = WINDOWS[window]
    if start is None:
        return pd.Series(True, index=events.index)
    return events.departure_seconds.ge(start) & events.departure_seconds.lt(end)

def classify_active_events(raw_events, selected_trips, stop_lookup):
    """Classify a complete feed's active stop sequences, independent of row order."""
    require(len(raw_events) > 0, "No active stop-time rows found.")
    require(set(RAW_EVENT_COLUMNS + ["feed_id", "source_line_number"]).issubset(raw_events.columns),
            "Incomplete active-event schema.")
    require_key(stop_lookup, STOP_KEYS, "stop lookup")
    require(stop_lookup.stop_key.eq(stop_lookup.feed_id + ":" + stop_lookup.stop_id).all(), "Stop namespace is inconsistent.")
    events = raw_events.copy()
    require(events.feed_id.nunique() == 1, "Process each operational feed separately.")
    feed_id = str(events.feed_id.iloc[0])
    require(selected_trips.feed_id.eq(feed_id).all(), "Mixed trip namespaces.")
    require_key(selected_trips, ["feed_id", "trip_id"], "selected trips")

    seq_text = events.stop_sequence.astype("string")
    require(seq_text.str.fullmatch(r"[0-9]+").all(), "Stop sequence must be a non-negative integer.")
    events["stop_sequence"] = pd.to_numeric(seq_text, errors="raise").astype("int64")
    require(not events.duplicated(EVENT_KEYS).any(), "Duplicate event key, including across read chunks.")
    require(set(events.trip_id) == set(selected_trips.trip_id), "Missing or unexpected active trip stop times.")
    require(events.stop_id.ne("").all(), "Empty stop identifier.")
    events["arrival_seconds"] = seconds_from_gtfs(events.arrival_time)
    events["departure_seconds"] = seconds_from_gtfs(events.departure_time)
    require(events.arrival_seconds.le(events.departure_seconds).all(), "Arrival is later than departure at a stop.")
    for field in ["pickup_type", "drop_off_type"]:
        require(events[field].astype("string").isin(["", "0", "1", "2", "3"]).all(),
                f"Unexpected {field} code.")
        events[field + "_effective"] = events[field].replace("", "0")

    # This maximum uses the FULL active trip, including stops outside our LGAs/window.
    by_trip = events.groupby("trip_id", sort=False)
    events["trip_last_sequence"] = by_trip.stop_sequence.transform("max")
    events["has_onward_stop"] = events.stop_sequence.lt(events.trip_last_sequence)
    terminals = events.loc[~events.has_onward_stop]
    require(len(terminals) == len(selected_trips) and terminals.trip_id.is_unique,
            "Expected exactly one final sequence per active trip.")
    # Independent max check after sorting. No contiguous sequence numbering is assumed.
    sorted_last = events.sort_values(["trip_id", "stop_sequence"]).groupby("trip_id", sort=False).tail(1)
    require(set(zip(sorted_last.trip_id, sorted_last.stop_sequence))
            == set(zip(terminals.trip_id, terminals.stop_sequence)), "Terminal detection disagrees.")

    trip_fields = ["feed_id", "trip_id", "trip_key", "route_id", "route_key",
                   "service_category", "is_labelled_replacement_bus"]
    before_rows = len(events)
    events = events.merge(selected_trips[trip_fields], on=["feed_id", "trip_id"],
                          how="left", validate="many_to_one", indicator="_trip_join")
    require(events._trip_join.eq("both").all(), "Unmatched active trip.")
    events = events.drop(columns="_trip_join")
    events = events.merge(stop_lookup[STOP_COLUMNS], on=STOP_KEYS,
                          how="left", validate="many_to_one", indicator="_stop_join")
    require(len(events) == before_rows and events._stop_join.eq("both").all(),
            "Missing or ambiguous feed/stop lookup; outside status is different from a missing key.")
    events = events.drop(columns="_stop_join")
    events["regular_pickup"] = events.pickup_type_effective.eq("0")
    assigned = events.spatial_match_status.eq("matched_within")
    events["selection_outcome"] = np.select(
        [
            (~events.has_onward_stop).to_numpy(dtype=bool),
            events.pickup_type_effective.eq("1").to_numpy(dtype=bool),
            events.pickup_type_effective.isin(["2", "3"]).to_numpy(dtype=bool),
            (~assigned).to_numpy(dtype=bool),
        ],
        OUTCOMES[:-1], default="counted_regular_pickup",
    )
    counted = events.selection_outcome.eq("counted_regular_pickup")
    require(counted.eq(events.has_onward_stop & events.regular_pickup & assigned).all(),
            "Selection outcome differs from the declared rule.")
    require(events.loc[counted, "lga_code_2025"].ne("").all(), "Counted event has no LGA.")
    return events

def summarize_events(events):
    """Return small analytical tables; never retain all feeds' raw events together."""
    lga_parts, stop_parts, membership_parts = [], [], []
    audit_rows, network_rows, sample_parts = [], [], []
    sample_columns = [
        *EVENT_KEYS, "source_line_number", "stop_id", "stop_key", "trip_key",
        "route_key", "service_category", "arrival_time", "departure_time",
        "departure_seconds", "pickup_type", "drop_off_type", "trip_last_sequence",
        "has_onward_stop", "lga_code_2025", "abs_lga_name", "spatial_match_status",
        "near_boundary_10m", "selection_outcome",
    ]
    categories = events[["feed_id", "service_category"]].drop_duplicates()
    for window in WINDOWS:
        window_events = events.loc[in_window(events, window)].copy()
        for cat in categories.itertuples(index=False):
            subset = window_events.loc[window_events.service_category.eq(cat.service_category)]
            counts = subset.selection_outcome.value_counts()
            partition = {name: int(counts.get(name, 0)) for name in OUTCOMES}
            require(sum(partition.values()) == len(subset), "Exclusive selection outcomes do not reconcile.")
            audit_rows.append({
                "feed_id": cat.feed_id, "service_category": cat.service_category, "window": window,
                "active_stop_time_rows_in_window": len(subset), **partition,
            })
            chosen = subset.loc[subset.selection_outcome.eq("counted_regular_pickup")]
            network_rows.append({
                "feed_id": cat.feed_id, "service_category": cat.service_category, "window": window,
                "eligible_departure_events": len(chosen),
                "unique_trip_records": chosen.trip_key.nunique(),
                "served_stop_records": chosen.stop_key.nunique(),
                "unique_route_records": chosen.route_key.nunique(),
                "near_boundary_events": int(chosen.near_boundary_10m.sum()),
                "extended_time_events": int(chosen.departure_seconds.ge(86400).sum()),
            })
            # Traceable examples, NOT a substitute for the full-table calculation.
            for outcome in OUTCOMES:
                sample = subset.loc[subset.selection_outcome.eq(outcome), sample_columns].head(3).copy()
                if not sample.empty:
                    sample["window"] = window
                    sample_parts.append(sample)

        chosen = window_events.loc[
            window_events.selection_outcome.eq("counted_regular_pickup")
        ].copy()
        chosen["window"] = window
        chosen["extended_time_event"] = chosen.departure_seconds.ge(86400)
        if not chosen.empty:
            lga_parts.append(chosen.groupby(LGA_GROUP, sort=True).agg(
                eligible_departure_events=("trip_key", "size"),
                unique_trip_records=("trip_key", "nunique"),
                served_stop_records=("stop_key", "nunique"),
                unique_route_records=("route_key", "nunique"),
                near_boundary_events=("near_boundary_10m", "sum"),
                extended_time_events=("extended_time_event", "sum"),
            ).reset_index())
            stop_parts.append(chosen.groupby(
                ["feed_id", "stop_id", "stop_key", "lga_code_2025", "service_category", "window"],
                sort=True,
            ).agg(
                eligible_departure_events=("trip_key", "size"),
                unique_trip_records=("trip_key", "nunique"),
                unique_route_records=("route_key", "nunique"),
                first_departure_seconds=("departure_seconds", "min"),
                last_departure_seconds=("departure_seconds", "max"),
                near_boundary_10m=("near_boundary_10m", "first"),
            ).reset_index())
            membership_parts.append(chosen[
                ["lga_code_2025", "feed_id", "service_category", "window", "trip_key", "route_key"]
            ].drop_duplicates())

    trip_scope = events.groupby(
        ["feed_id", "trip_key", "route_key", "service_category"], sort=True
    ).agg(
        complete_stop_time_rows=("stop_sequence", "size"),
        first_sequence=("stop_sequence", "min"), final_sequence=("stop_sequence", "max"),
        first_departure_seconds=("departure_seconds", "min"),
        last_departure_seconds=("departure_seconds", "max"),
    ).reset_index()
    # Count all source events, including excluded/outside records, in the trip-level audit.
    require(int(trip_scope.complete_stop_time_rows.sum()) == len(events), "Trip-scope row counts differ.")
    return {
        "lga": pd.concat(lga_parts, ignore_index=True) if lga_parts else pd.DataFrame(columns=LGA_GROUP + COUNT_FIELDS),
        "stops": pd.concat(stop_parts, ignore_index=True) if stop_parts else pd.DataFrame(columns=["feed_id", "stop_id", "stop_key", "lga_code_2025", "service_category", "window", "eligible_departure_events", "unique_trip_records", "unique_route_records", "first_departure_seconds", "last_departure_seconds", "near_boundary_10m"]),
        "memberships": pd.concat(membership_parts, ignore_index=True) if membership_parts else pd.DataFrame(columns=[*LGA_GROUP, "trip_key", "route_key"]),
        "filter_audit": pd.DataFrame(audit_rows),
        "network": pd.DataFrame(network_rows),
        "examples": pd.concat(sample_parts, ignore_index=True) if sample_parts else pd.DataFrame(),
        "trip_scope": trip_scope,
    }

@contextmanager
def open_stop_time_chunks(path: Path, feed_id: str, chunk_rows: int = 100_000):
    require(type(chunk_rows) is int and chunk_rows > 0, "Chunk size must be a positive integer.")
    with open_feed(path, feed_id) as inner:
        require(inner.namelist().count("stop_times.txt") == 1, "Missing stop_times.txt.")
        with inner.open("stop_times.txt") as handle:
            header = pd.read_csv(handle, nrows=0).columns.tolist()
        require(set(RAW_EVENT_COLUMNS).issubset(header), "Missing audited stop-time fields.")
        unsupported = {"location_id", "location_group_id", "start_pickup_drop_off_window", "end_pickup_drop_off_window", "pickup_booking_rule_id", "drop_off_booking_rule_id", "continuous_pickup", "continuous_drop_off"}
        require(not unsupported.intersection(header), "Flexible/continuous-service fields require a reviewed extension.")
        with inner.open("stop_times.txt") as handle:
            with pd.read_csv(handle, usecols=RAW_EVENT_COLUMNS, dtype="string", keep_default_na=False,
                             encoding="utf-8-sig", chunksize=chunk_rows) as reader:
                yield reader

def scan_service_feed(path: Path, feed_id: str, selected: pd.DataFrame, stops_lookup: pd.DataFrame, expected_rows: int, chunk_rows: int = 100_000):
    """Scan all rows once, retaining only active trips in this feed."""
    wanted = set(selected.trip_id)
    started = perf_counter()
    pieces, total_rows, retained = [], 0, 0
    print(f"Scanning feed {feed_id} stop_times.txt...", flush=True)
    with open_stop_time_chunks(path, feed_id, chunk_rows) as chunks:
        for number, chunk in enumerate(chunks, start=1):
            part = chunk.loc[chunk.trip_id.isin(wanted)].copy()
            # pandas chunk indexes are global here; use explicit offsets instead of relying on that.
            positions = np.flatnonzero(chunk.trip_id.isin(wanted).to_numpy(dtype=bool))
            part["source_line_number"] = total_rows + positions + 2  # header is line 1
            part["feed_id"] = pd.Series(feed_id, index=part.index, dtype="string")
            if not part.empty:
                pieces.append(part)
                retained += len(part)
            total_rows += len(chunk)
            if number == 1 or number % 10 == 0:
                print(f"  Read {total_rows:,} source rows; retained {retained:,} active-trip rows.", flush=True)
    require(total_rows == expected_rows, f"Source row count changed in feed {feed_id}.")
    require(pieces, f"No active records in feed {feed_id}.")
    raw_active = pd.concat(pieces, ignore_index=True)
    del pieces
    events = classify_active_events(raw_active, selected, stops_lookup)
    del raw_active
    results = summarize_events(events)
    results["scan"] = {
        "feed_id": feed_id, "source_stop_time_rows_scanned": total_rows,
        "active_trip_records": len(selected), "active_stop_time_rows": len(events),
        "terminal_trip_records": int((~events.has_onward_stop).sum()),
        "after_midnight_active_rows": int(events.departure_seconds.ge(86400).sum()),
        "minimum_departure_seconds": int(events.departure_seconds.min()),
        "maximum_departure_seconds": int(events.departure_seconds.max()),
    }
    print(f"Feed {feed_id} done: {total_rows:,} rows scanned; {len(events):,} active rows; "
          f"{perf_counter()-started:.1f}s.", flush=True)
    # Only small aggregates, trip memberships and trace examples survive this function.
    return results

def categorize_trips(active: pd.DataFrame) -> pd.DataFrame:
    result = active.copy(deep=True)
    require_key(result, ["feed_id", "trip_id"], "active trips")
    require(result.feed_id.isin(["2", "3", "4"]).all(), "Unreviewed service feed.")
    require(result.is_labelled_replacement_bus.dropna().isin([True,False]).all() and result.is_labelled_replacement_bus.notna().all(), "Replacement flag must be boolean.")
    result["service_category"] = result.feed_id.map({"2":"train_not_labelled_replacement", "3":"tram", "4":"myki_bus"})
    require(result.loc[result.is_labelled_replacement_bus, "feed_id"].eq("2").all(), "Unexpected replacement feed.")
    result.loc[result.is_labelled_replacement_bus, "service_category"] = "labelled_replacement_bus"
    return result


def combine_service_results(feed_results: dict, active_for_service: pd.DataFrame, lga_inventory: pd.DataFrame, service_date: date, expected_scan_rows: int) -> dict[str, pd.DataFrame]:
    """Complete the zero grid and reconcile independent trip/stop/LGA summaries."""
    FEED_IDS = tuple(feed_results)

    def combine_result(name):
        return pd.concat([feed_results[f][name] for f in FEED_IDS], ignore_index=True)
    lga_nonzero = combine_result('lga')
    stop_service = combine_result('stops')
    trip_lga_memberships = combine_result('memberships')
    filter_audit = combine_result('filter_audit')
    network_service = combine_result('network')
    trace_examples = combine_result('examples')
    trip_stop_scope = combine_result('trip_scope')
    scan_summary = pd.DataFrame([feed_results[f]['scan'] for f in FEED_IDS])
    require(int(scan_summary.source_stop_time_rows_scanned.sum()) == expected_scan_rows, 'Incomplete source scan.')
    require(int(scan_summary.active_trip_records.sum()) == len(active_for_service), 'Active-trip reconciliation failed.')
    require(int(trip_stop_scope.complete_stop_time_rows.sum()) == int(scan_summary.active_stop_time_rows.sum()), 'Active stop-time rows do not reconcile.')
    require_key(trip_stop_scope, ['trip_key'], 'complete-trip scope')
    require(set(trip_stop_scope.trip_key) == set(active_for_service.trip_key), 'A complete trip is missing.')
    require_key(lga_nonzero, LGA_GROUP, 'nonzero LGA aggregates')
    require_key(trip_lga_memberships, LGA_GROUP + ['trip_key'], 'trip/LGA/window memberships')
    category_table = pd.DataFrame([{'service_category': category, 'feed_id': feed} for category, feed in CATEGORY_FEED.items()])
    grid = lga_inventory.merge(category_table, how='cross').merge(pd.DataFrame({'window': list(WINDOWS)}), how='cross')
    lga_service = grid.merge(lga_nonzero, on=LGA_GROUP, how='left', validate='one_to_one')
    for col in COUNT_FIELDS:
        lga_service[col] = lga_service[col].fillna(0).astype('int64')
    lga_service['eligible_events_excluding_near_boundary'] = lga_service.eligible_departure_events - lga_service.near_boundary_events
    lga_service = lga_service.sort_values(['window', 'lga_code_2025', 'service_category'], kind='stable').reset_index(drop=True)
    require(len(lga_service) == len(lga_inventory) * len(CATEGORY_FEED) * len(WINDOWS), 'Incomplete LGA/category/window grid.')
    require_key(lga_service, LGA_GROUP, 'complete LGA service table')
    require(lga_service[COUNT_FIELDS].ge(0).all().all(), 'Negative summary count.')
    for col in COUNT_FIELDS[1:]:
        require(lga_service[col].le(lga_service.eligible_departure_events).all(), f'{col} exceeds the counted event total.')
    reference = lga_service.set_index(LGA_GROUP)
    membership_counts = trip_lga_memberships.groupby(LGA_GROUP).trip_key.nunique().reindex(reference.index, fill_value=0)
    stop_event_counts = stop_service.groupby(LGA_GROUP).eligible_departure_events.sum().reindex(reference.index, fill_value=0)
    stop_record_counts = stop_service.groupby(LGA_GROUP).stop_key.nunique().reindex(reference.index, fill_value=0)
    require(np.array_equal(reference.unique_trip_records.to_numpy(), membership_counts.to_numpy()), 'LGA trip counts differ from independent membership counts.')
    require(np.array_equal(reference.eligible_departure_events.to_numpy(), stop_event_counts.to_numpy()), 'LGA event counts differ from summed stop-level events.')
    require(np.array_equal(reference.served_stop_records.to_numpy(), stop_record_counts.to_numpy()), 'LGA stop counts differ from independent stop identities.')
    net_keys = ['feed_id', 'service_category', 'window']
    network_reference = network_service.set_index(net_keys)
    lga_event_sums = lga_service.groupby(net_keys).eligible_departure_events.sum().reindex(network_reference.index, fill_value=0)
    network_trip_counts = trip_lga_memberships.groupby(net_keys).trip_key.nunique().reindex(network_reference.index, fill_value=0)
    require(np.array_equal(network_reference.eligible_departure_events, lga_event_sums), 'An eligible event was lost or counted in multiple LGAs.')
    require(np.array_equal(network_reference.unique_trip_records, network_trip_counts), 'Network trips were incorrectly summed across LGAs.')
    audit_reference = filter_audit.set_index(net_keys)
    require(np.array_equal(audit_reference.counted_regular_pickup.reindex(network_reference.index), network_reference.eligible_departure_events), 'Filter-audit counted events disagree.')
    require(filter_audit[OUTCOMES].sum(axis=1).eq(filter_audit.active_stop_time_rows_in_window).all(), 'Filter audit is not an exhaustive, exclusive partition.')
    require(int(filter_audit.loc[filter_audit.window.eq('service_day'), 'terminal_trip_record'].sum()) == len(active_for_service), 'Full service day must exclude one terminal per active trip.')
    all_day = lga_service.loc[lga_service.window.eq('service_day')].set_index(['lga_code_2025', 'service_category'])
    morning = lga_service.loc[lga_service.window.eq('am_peak_0700_0900')].set_index(['lga_code_2025', 'service_category'])
    require(morning[COUNT_FIELDS].le(all_day[COUNT_FIELDS]).all().all(), 'Morning is not a subset of service day.')
    require(morning.extended_time_events.eq(0).all(), 'Extended times were incorrectly wrapped into the morning window.')
    for table in [lga_service, stop_service, trip_lga_memberships, filter_audit, network_service, trace_examples, trip_stop_scope, scan_summary]:
        table['service_date'] = service_date.isoformat()
        table['agency_timezone'] = 'Australia/Melbourne'
    exports = {
        "active_trip_lookup.csv": active_for_service,
        "trip_stop_scope.csv": trip_stop_scope,
        "lga_service_indicators.csv": lga_service,
        "stop_service_indicators.csv": stop_service,
        "trip_lga_memberships.csv": trip_lga_memberships,
        "feed_service_summary.csv": network_service,
        "event_filter_audit.csv": filter_audit,
        "scan_summary.csv": scan_summary,
        "event_trace_examples.csv": trace_examples,
    }
    return exports

