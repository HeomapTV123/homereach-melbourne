"""Real-data Streamlit pages. Read verified bundles; never run a pipeline on rerun."""
from __future__ import annotations
from pathlib import Path
import os
import pandas as pd
import streamlit as st
from packaging.version import Version

from .analysis import AM_WINDOW, DAY_WINDOW, CATEGORY_LABELS, CODE, filter_comparison
from .bundle import ExplorerBundle, bundle_signature, load_bundle
from .charts import category_chart, rent_history_chart, rent_map, rent_service_scatter

DISPLAY_COLUMNS = {
    "rental_area_name": "Rental-source LGA", "abs_lga_name": "ABS LGA name", CODE: "ABS 2025 code",
    "median_weekly_rent": "Median rent (AUD/week)", "published_count": "Published rental count",
    "am_unique_trip_records": "Distinct AM trips in LGA", "am_departure_events": "AM departure events",
    "am_served_stop_records": "Stop records with AM events", "assigned_stop_records": "All assigned stop records",
    "assigned_records_without_counted_am_event": "Assigned records with no AM event",
    "mean_am_events_per_assigned_stop_record": "Mean AM events / all assigned records",
    "mean_am_events_per_served_stop_record": "Mean AM events / served records",
    "quarter": "Rental reporting quarter", "transport_service_date": "Transport service date",
    "transport_timezone": "Transport timezone", "source_region": "Rental-source region",
}


def period_banner() -> None:
    st.caption("RENT 2025Q3 · TWO-BEDROOM FLATS  |  TRANSPORT 13 OCT 2026 · 07:00–09:00 MELBOURNE TIME  |  ABS BOUNDARIES 2025")
    st.info("These are differently dated historical snapshots, not live listings. "
            "This explorer compares published statistics; it does not recommend an area or predict rent.")


def csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False, date_format="%Y-%m-%d", lineterminator="\n").encode("utf-8-sig")


def formatted_table(frame: pd.DataFrame, fields: list[str]) -> None:
    shown = frame[fields].rename(columns=DISPLAY_COLUMNS)
    st.dataframe(shown, hide_index=True, width="stretch",
                 column_config={"Median rent (AUD/week)": st.column_config.NumberColumn(format="$%.0f"),
                                "Mean AM events / all assigned records": st.column_config.NumberColumn(format="%.2f"),
                                "Mean AM events / served records": st.column_config.NumberColumn(format="%.2f")})


def render_compare(bundle: ExplorerBundle) -> None:
    st.title("Compare Melbourne LGAs")
    period_banner()
    areas = bundle.areas
    st.write("Explore all 31 areas, or narrow the comparison using published rent and scheduled service. "
             "The table starts in alphabetical order—not a best-to-worst ranking.")
    c1, c2 = st.columns([2, 1])
    with c1:
        regions = st.multiselect("Rental-source regions", sorted(areas.source_region.unique()),
                                  default=sorted(areas.source_region.unique()), key="compare_regions")
    with c2:
        minimum = st.number_input("Minimum distinct AM trips in the LGA", min_value=0, max_value=100000,
                                  value=0, step=25, key="compare_min_trips")
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        use_ceiling = st.checkbox("Apply a published-rent ceiling", value=False, key="compare_use_ceiling")
    with c2:
        ceiling = st.number_input("Median-rent ceiling (AUD/week)", min_value=0, max_value=3000,
                                  value=600, step=10, disabled=not use_ceiling, key="compare_ceiling")
    with c3:
        sort_options = {"LGA name (A–Z)": ("rental_area_name", True),
                        "Published rent (low to high)": ("median_weekly_rent", True),
                        "Distinct AM trips (high to low)": ("am_unique_trip_records", False),
                        "AM departure events (high to low)": ("am_departure_events", False)}
        sort_label = st.selectbox("Sort the comparison", list(sort_options), key="compare_sort")
    st.caption("The ceiling filters an area's published median. It does not establish that an available property "
               "meets your budget or that this area is affordable relative to your income.")
    field, direction = sort_options[sort_label]
    selected = filter_comparison(areas, regions=regions, maximum_rent=float(ceiling) if use_ceiling else None,
                                 minimum_am_trips=int(minimum), sort_by=field, ascending=direction)
    if selected.empty:
        st.warning("No LGAs match these filters. Select a source region, raise the rent ceiling, or lower the trip minimum.")
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("LGAs shown", f"{len(selected)} / {len(areas)}")
    c2.metric("Lowest displayed LGA median", f"${selected.median_weekly_rent.min():,.0f}/week")
    c3.metric("Highest displayed LGA median", f"${selected.median_weekly_rent.max():,.0f}/week")
    fields = ["rental_area_name", "median_weekly_rent", "published_count", "am_unique_trip_records",
              "am_departure_events", "am_served_stop_records", "quarter", "transport_service_date"]
    formatted_table(selected, fields)
    st.caption("Distinct trips can visit multiple LGAs. Do not add the LGA trip counts to estimate a study-area total.")
    st.download_button("Download the displayed comparison (CSV)", csv_bytes(selected),
                       file_name="homereach_comparison_rent_2025Q3_transport_2026-10-13.csv",
                       mime="text/csv", key="compare_download")
    st.subheader("Published rent versus scheduled morning trips")
    st.plotly_chart(rent_service_scatter(selected), width="stretch", key="comparison_scatter")
    st.caption("Each point is one LGA. Hover for its original source periods. "
               "A higher trip count is not proof of shorter waits, reliable operations or a useful journey to your destination.")


def render_area(bundle: ExplorerBundle) -> None:
    st.title("Area details")
    period_banner()
    areas = bundle.areas.sort_values("rental_area_name").reset_index(drop=True)
    codes = areas[CODE].tolist(); labels = areas.set_index(CODE).rental_area_name.to_dict()
    default = next((i for i, c in enumerate(codes) if labels[c] == "Melbourne"), 0)
    code = st.selectbox("Choose an LGA", codes, index=default, format_func=lambda c: labels[c], key="area_code")
    row = areas.loc[areas[CODE].eq(code)].iloc[0]
    st.subheader(str(row.rental_area_name))
    st.caption(f"ABS 2025 code {code} · Official boundary name: {row.abs_lga_name} · {row.source_region}")
    cols = st.columns(3)
    cols[0].metric("2025Q3 median weekly rent", f"${row.median_weekly_rent:,.0f}")
    cols[1].metric("Distinct AM trips in this LGA", f"{int(row.am_unique_trip_records):,}")
    cols[2].metric("Stop records with counted AM events", f"{int(row.am_served_stop_records):,}")
    st.subheader("Rental history")
    history = bundle.tables["rental_history.csv"]
    history = history.loc[history[CODE].eq(code)].sort_values("quarter_end").copy()
    period = st.selectbox("History shown", ["Last 5 years", "Last 10 years", "All available quarters"], key="history_period")
    shown = history.tail(20 if period == "Last 5 years" else 40) if period != "All available quarters" else history
    st.plotly_chart(rent_history_chart(shown), width="stretch", key="area_history")
    st.caption("Nominal published medians of new lettings in each quarter, not the history of a fixed property "
               "and not adjusted for inflation. The 2026 transport snapshot is not added to past rental quarters.")
    st.download_button("Download this LGA's full rental history", csv_bytes(history),
                       file_name=f"rental_history_{code}.csv", mime="text/csv", key="area_history_download")
    st.subheader("Scheduled transport breakdown")
    option = st.radio("Service window on 13 October 2026", ["Morning 07:00–09:00", "Complete GTFS service day"],
                      horizontal=True, key="area_window")
    window = AM_WINDOW if option.startswith("Morning") else DAY_WINDOW
    cats = bundle.tables["lga_service_categories.csv"]
    cats = cats.loc[cats[CODE].eq(code) & cats.window.eq(window)].copy()
    st.plotly_chart(category_chart(cats), width="stretch", key="area_categories")
    table = cats.assign(service_category=cats.service_category.map(CATEGORY_LABELS))[
        ["service_category", "eligible_departure_events", "unique_trip_records", "served_stop_records", "unique_route_records"]]
    table.columns = ["Service category", "Departure events", "Distinct trip records", "Served stop records", "Distinct route IDs"]
    st.dataframe(table, hide_index=True, width="stretch")
    st.caption("Feed 2 is labelled cautiously: not explicitly labelled replacement is not a complete mode audit. "
               "The complete service day retains 24:00+ times, which can extend into the next calendar day.")
    with st.expander("Stop-record denominators and source evidence"):
        formatted_table(areas.loc[areas[CODE].eq(code)], ["rental_area_name", "assigned_stop_records",
                        "am_served_stop_records", "assigned_records_without_counted_am_event",
                        "mean_am_events_per_assigned_stop_record", "mean_am_events_per_served_stop_record"])
        st.write("These averages count source records, not unique physical stations, residents, waiting times or walking access.")
        st.code(f"Workbook: {row.source_file}\nWorksheet: {row.source_sheet}\n"
                f"Median cell: {row.source_median_cell}\nCount cell: {row.source_count_cell}\n"
                f"Rental period: {row.quarter}\nTransport date: {row.transport_service_date}", language=None)


def render_map(bundle: ExplorerBundle) -> None:
    st.title("Rental map")
    period_banner()
    st.write("All 31 selected LGAs, coloured by their September 2025 median weekly rent for two-bedroom flats.")
    online = st.checkbox("Use online street/place background tiles", value=False, key="map_online")
    st.caption("Off: no external map tiles. On: your browser requests tiles from the map provider. "
               "Polygon size represents area, not rent or rental count.")
    st.plotly_chart(rent_map(bundle.areas, bundle.geometry, online_basemap=online),
                    width="stretch", key="rental_map")
    st.caption("Rents: DFFH. Boundaries: ABS ASGS LGA 2025, CC BY 4.0. "
               "Statistical boundaries are not legal boundary definitions. No simplification or geometry repair was applied.")
    with st.expander("Map not displaying? View the same source values as a table"):
        st.write("This interactive map needs browser WebGL support. A white background is expected with tiles off, "
                 "but coloured polygons should still appear. The table is an equivalent-value fallback, not a different dataset.")
        formatted_table(bundle.areas, ["rental_area_name", CODE, "median_weekly_rent", "published_count", "quarter"])


def render_method(bundle: ExplorerBundle) -> None:
    st.title("Data and methodology")
    period_banner()
    manifest = bundle.manifest
    st.subheader("Three distinct source periods")
    periods = bundle.tables["source_periods.csv"]
    st.dataframe(periods[["component", "period", "scope"]], hide_index=True, width="stretch")
    st.subheader("What one departure event means")
    st.write("An active feed/trip/stop-sequence record is counted when ordinary pickup is allowed, the complete trip "
             "has a later stop, and the stop is inside a selected LGA. Terminal detection happens before geographic "
             "or time filtering. Calendar exceptions are applied. Labelled replacement buses stay separate.")
    st.subheader("A trip may serve several LGAs")
    totals = bundle.tables["study_area_reconciliation.csv"]
    am = totals.loc[totals.window.eq(AM_WINDOW)].iloc[0]
    st.write(f"Across the whole 31-LGA study area there are **{int(am.distinct_study_area_trips):,} distinct counted "
             f"AM trips**. Adding the LGA-specific trip counts gives "
             f"**{int(am.sum_of_lga_trip_counts_not_a_study_area_total):,}**, which double-counts trips visiting multiple areas.")
    st.subheader("Limits that remain visible")
    st.markdown("""
- Rents are historical nominal area medians, not available listings, fixed-property histories or a household-income affordability measure.
- Transport counts are scheduled supply for one service date, not actual departures, riders, vehicles, waiting times, reliability or commute times.
- Large LGAs and routes with many local stop visits can have higher raw counts. No population or residential-catchment weighting is applied.
- Stops outside an LGA can serve its residents. Stored platform records are not unique physical stations. Near-boundary flags are sensitivity diagnostics.
- Unknown accessibility information is not treated as inaccessible. No accessible-journey assessment is made.
- The newer transport snapshot is never backfilled into historical rental-model evaluation. No combined score, forecast or best-area label is produced.
""")
    st.subheader("Build evidence")
    st.write(f"Explorer bundle created (UTC): `{manifest['created_at_utc']}`")
    st.write(f"Notebook 08 comparison tables matched at build time: **{len(manifest['notebook_tables_compared'])}/6**.")
    st.caption("Fingerprints detect changes relative to local build records; they are not a publisher signature or an independent certification.")
    st.json(manifest["quality"], expanded=False)
    st.download_button("Download the explorer build manifest", __import__("json").dumps(manifest, indent=2),
                       file_name="explorer_manifest.json", mime="application/json", key="manifest_download")
    st.subheader("Original sources")
    for row in periods.itertuples(index=False):
        st.markdown(f"**{row.component.capitalize()}** · {row.period}")
        st.write(row.publisher_page)
        st.caption(f"Source file: {row.source_file} · SHA-256: {row.source_sha256}")
    st.info("The original synthetic demo remains at app/Home.py and is not loaded anywhere in this explorer.")


@st.cache_data(show_spinner=False)
def cached_bundle(root_string: str, signature: str) -> ExplorerBundle:
    return load_bundle(Path(root_string), expected_signature=signature)


def run_app(default_root: Path) -> None:
    st.set_page_config(page_title="HomeReach Melbourne | Real-data explorer", page_icon="🏠", layout="wide")
    if Version(st.__version__) < Version("1.50.0"):
        st.error("This explorer needs Streamlit 1.50 or later for width='stretch'. Report your installed version before changing the environment.")
        st.stop()
    root = Path(os.environ.get("HOMEREACH_PROJECT_ROOT", str(default_root))).resolve()
    try:
        signature = bundle_signature(root)
        bundle = cached_bundle(str(root), signature)
    except (OSError, ValueError, KeyError, TypeError) as error:
        st.title("HomeReach Melbourne")
        st.error(f"The verified explorer bundle is not ready: {error}")
        st.write("Run this from the project root in your homereach environment, then refresh the page:")
        st.code("python scripts/build_explorer_data.py", language="bash")
        st.info("No synthetic fallback was loaded. Do not edit fingerprints to bypass a failed data check.")
        st.stop()
    with st.sidebar:
        st.header("HomeReach Melbourne")
        st.caption("REAL-DATA EXPLORER · LOCAL BUILD")
        st.caption("31 source-group LGAs\n\nTwo-bedroom flats\n\nNo scores or predictions")
    def compare_page(): render_compare(bundle)
    def area_page(): render_area(bundle)
    def map_page(): render_map(bundle)
    def method_page(): render_method(bundle)
    page = st.navigation([
        st.Page(compare_page, title="Compare LGAs", icon=":material/compare_arrows:", default=True),
        st.Page(area_page, title="Area details", icon=":material/location_city:", url_path="area"),
        st.Page(map_page, title="Rental map", icon=":material/map:", url_path="map"),
        st.Page(method_page, title="Data and methodology", icon=":material/info:", url_path="methodology"),
    ])
    page.run()
