"""Plotly figures with explicit periods and no synthetic scores or trend forecasts."""
from __future__ import annotations
from copy import deepcopy
import pandas as pd
import plotly.graph_objects as go
from .analysis import CODE, CATEGORY_LABELS


def rent_service_scatter(frame: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for region, rows in frame.groupby("source_region", sort=True):
        fig.add_trace(go.Scatter(
            x=rows.median_weekly_rent, y=rows.am_unique_trip_records,
            mode="markers", name=str(region), marker={"size": 11},
            customdata=rows[["rental_area_name", CODE, "quarter", "transport_service_date", "am_departure_events"]].to_numpy(),
            hovertemplate=("%{customdata[0]} (%{customdata[1]})<br>Rent: $%{x:.0f}/week · %{customdata[2]}"
                           "<br>Distinct AM trips: %{y:,} · %{customdata[3]}"
                           "<br>AM departure events: %{customdata[4]:,}<extra></extra>")))
    fig.update_layout(height=460, margin={"l": 60, "r": 20, "t": 35, "b": 90},
                      legend={"orientation": "h", "y": -0.25})
    fig.update_xaxes(title="Published median weekly rent (AUD) · 2025Q3", tickprefix="$")
    fig.update_yaxes(title="Distinct AM trip records · 13 Oct 2026", rangemode="tozero")
    return fig


def rent_history_chart(history: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for name, rows in history.groupby("rental_area_name", sort=True):
        rows = rows.sort_values("quarter_end", kind="stable")
        fig.add_trace(go.Scatter(x=rows.quarter_end, y=rows.median_weekly_rent, mode="lines", name=str(name),
                                customdata=rows[["quarter", "published_count", "source_median_cell"]].to_numpy(),
                                hovertemplate=("%{customdata[0]}<br>$%{y:.0f}/week"
                                               "<br>Published count: %{customdata[1]:,}"
                                               "<br>Excel cell: %{customdata[2]}<extra>%{fullData.name}</extra>")))
    fig.update_layout(height=400, margin={"l": 55, "r": 20, "t": 20, "b": 45})
    fig.update_xaxes(title="Reporting quarter")
    fig.update_yaxes(title="Nominal median rent (AUD/week)", tickprefix="$")
    return fig


def category_chart(frame: pd.DataFrame) -> go.Figure:
    rows = frame.copy()
    rows["label"] = rows.service_category.map(CATEGORY_LABELS)
    rows = rows.sort_values("label", kind="stable")
    fig = go.Figure(go.Bar(y=rows.label, x=rows.eligible_departure_events, orientation="h",
                          customdata=rows[["unique_trip_records", "served_stop_records"]].to_numpy(),
                          hovertemplate=("%{y}<br>Eligible departure events: %{x:,}"
                                         "<br>Distinct contributing trips: %{customdata[0]:,}"
                                         "<br>Served records: %{customdata[1]:,}<extra></extra>")))
    fig.update_layout(height=330, margin={"l": 30, "r": 20, "t": 20, "b": 45})
    fig.update_xaxes(title="Counted stop-level departure events", rangemode="tozero")
    return fig


def rent_map(frame: pd.DataFrame, geometry: dict, *, online_basemap: bool = False) -> go.Figure:
    """Use unchanged web polygons; rank/transport scores are not calculated."""
    if not hasattr(go, "Choroplethmap"):
        raise ValueError("The map needs Plotly 5.24 or later, as notebook 04 does.")
    ordered = frame.sort_values(CODE).reset_index(drop=True)
    fig = go.Figure(go.Choroplethmap(
        geojson=deepcopy(geometry), locations=ordered[CODE].tolist(), featureidkey=f"properties.{CODE}",
        z=ordered.median_weekly_rent.to_numpy(), marker_line_width=0.6, marker_opacity=0.85,
        colorbar={"title": {"text": "Rent<br>AUD/week"}},
        customdata=ordered[["rental_area_name", "published_count", "source_median_cell", "quarter"]].to_numpy(),
        hovertemplate=("%{customdata[0]} (%{location})<br>%{customdata[3]} · 2-bedroom flats"
                       "<br>Median: $%{z:.0f}/week<br>Published count: %{customdata[1]:,}"
                       "<br>Source: 2br Flat!%{customdata[2]}<extra></extra>")))
    fig.update_layout(map={"style": "carto-positron" if online_basemap else "white-bg",
                           "center": {"lat": -37.93, "lon": 145.06}, "zoom": 8.0},
                      height=650, margin={"l": 0, "r": 0, "t": 10, "b": 10}, uirevision="rent-2025q3")
    return fig
