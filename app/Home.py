from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from homereach.scoring import (
    linear_limit_score,
    robust_range_score,
    weighted_score,
)

st.set_page_config(
    page_title="HomeReach Melbourne",
    page_icon="🏠",
    layout="wide",
)

st.title("HomeReach Melbourne")
st.caption("Explainable rental and accessibility decision-support prototype")

sample_path = Path("data/sample/candidate_areas.csv")
if not sample_path.exists():
    st.error(f"Sample data is missing: {sample_path}")
    st.stop()

data = pd.read_csv(sample_path)

st.warning(
    "This starter page uses synthetic demonstration data. "
    "It is not a real ranking of Melbourne areas."
)

with st.sidebar:
    st.header("Your scenario")
    weekly_budget = st.slider(
        "Maximum weekly rent ($)",
        min_value=250,
        max_value=900,
        value=500,
        step=10,
    )
    max_commute = st.slider(
        "Preferred maximum commute (minutes)",
        min_value=15,
        max_value=90,
        value=45,
        step=5,
    )

    st.subheader("Importance weights")
    affordability_weight = st.slider("Affordability", 0, 100, 35)
    transport_weight = st.slider("Transport service", 0, 100, 25)
    commute_weight = st.slider("Commute", 0, 100, 20)
    environment_weight = st.slider("Environment", 0, 100, 10)
    stability_weight = st.slider("Rent stability", 0, 100, 10)

data["affordability_score"] = linear_limit_score(
    data["median_weekly_rent"],
    preferred_limit=weekly_budget,
)
data["commute_score"] = linear_limit_score(
    data["scheduled_commute_minutes"],
    preferred_limit=max_commute,
)
data["transport_score"] = robust_range_score(
    data["weekday_peak_departures"],
    higher_is_better=True,
)
data["environment_score"] = robust_range_score(
    data["vegetation_percent"],
    higher_is_better=True,
)
data["stability_score"] = robust_range_score(
    data["forecast_annual_growth_percent"],
    higher_is_better=False,
)

weights = {
    "affordability_score": affordability_weight,
    "transport_score": transport_weight,
    "commute_score": commute_weight,
    "environment_score": environment_weight,
    "stability_score": stability_weight,
}

try:
    ranked = weighted_score(data, weights)
except ValueError as error:
    st.error(str(error))
    st.stop()

ranked = ranked.sort_values(
    "overall_score",
    ascending=False,
).reset_index(drop=True)
ranked.insert(0, "rank", ranked.index + 1)

top = ranked.iloc[0]
metric_columns = st.columns(4)
metric_columns[0].metric("Top demo area", top["area_name"])
metric_columns[1].metric(
    "Overall score",
    f"{top['overall_score']:.1f}/100",
)
metric_columns[2].metric(
    "Weekly rent",
    f"${top['median_weekly_rent']:.0f}",
)
metric_columns[3].metric(
    "Scheduled commute",
    f"{top['scheduled_commute_minutes']:.0f} min",
)

st.subheader("Ranked demonstration areas")
display_columns = [
    "rank",
    "area_name",
    "overall_score",
    "median_weekly_rent",
    "scheduled_commute_minutes",
    "affordability_score",
    "transport_score",
    "commute_score",
    "environment_score",
    "stability_score",
]
st.dataframe(
    ranked[display_columns].style.format(
        {
            "overall_score": "{:.1f}",
            "median_weekly_rent": "${:.0f}",
            "scheduled_commute_minutes": "{:.0f}",
            "affordability_score": "{:.1f}",
            "transport_score": "{:.1f}",
            "commute_score": "{:.1f}",
            "environment_score": "{:.1f}",
            "stability_score": "{:.1f}",
        }
    ),
    use_container_width=True,
    hide_index=True,
)

st.subheader("Why the first area ranked highest")
explanation = pd.DataFrame(
    {
        "component": list(weights),
        "score": [top[column] for column in weights],
        "selected_weight": list(weights.values()),
    }
)
weight_sum = explanation["selected_weight"].sum()

if weight_sum > 0:
    explanation["normalised_weight"] = (
        explanation["selected_weight"] / weight_sum
    )
    explanation["weighted_contribution"] = (
        explanation["score"] * explanation["normalised_weight"]
    )
    explanation = explanation.sort_values(
        "weighted_contribution",
        ascending=False,
    )
    st.dataframe(
        explanation.style.format(
            {
                "score": "{:.1f}",
                "normalised_weight": "{:.1%}",
                "weighted_contribution": "{:.1f}",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

st.info(
    "Next milestone: replace every synthetic input column with a "
    "reproducible feature calculated from official source data."
)
