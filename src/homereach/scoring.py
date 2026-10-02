from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd


def linear_limit_score(
    values: pd.Series,
    preferred_limit: float,
) -> pd.Series:
    """
    Score a lower-is-better measure from 0 to 100.

    Zero receives 100, the preferred limit receives 50, and twice the
    preferred limit receives 0. This rule is intentionally transparent.
    """
    if preferred_limit <= 0:
        raise ValueError("preferred_limit must be greater than zero.")

    numeric = pd.to_numeric(values, errors="coerce")
    score = 100 - 50 * (numeric / preferred_limit)
    return score.clip(lower=0, upper=100)


def robust_range_score(
    values: pd.Series,
    *,
    higher_is_better: bool,
    lower_quantile: float = 0.05,
    upper_quantile: float = 0.95,
) -> pd.Series:
    """
    Convert a numeric feature to a 0–100 score using clipped quantiles.

    Quantile clipping stops one extreme area from compressing the scores
    of all other areas.
    """
    if not 0 <= lower_quantile < upper_quantile <= 1:
        raise ValueError("Quantiles must satisfy 0 <= lower < upper <= 1.")

    numeric = pd.to_numeric(values, errors="coerce")
    lower = numeric.quantile(lower_quantile)
    upper = numeric.quantile(upper_quantile)

    if pd.isna(lower) or pd.isna(upper):
        return pd.Series(np.nan, index=numeric.index, dtype=float)

    if np.isclose(lower, upper):
        return pd.Series(50.0, index=numeric.index, dtype=float)

    clipped = numeric.clip(lower=lower, upper=upper)
    score = 100 * (clipped - lower) / (upper - lower)

    if not higher_is_better:
        score = 100 - score

    return score.astype(float)


def normalise_weights(weights: Mapping[str, float]) -> dict[str, float]:
    """Validate non-negative weights and make them sum to one."""
    if not weights:
        raise ValueError("At least one score weight is required.")

    numeric = {name: float(value) for name, value in weights.items()}
    if any(value < 0 for value in numeric.values()):
        raise ValueError("Weights cannot be negative.")

    total = sum(numeric.values())
    if total <= 0:
        raise ValueError("At least one weight must be greater than zero.")

    return {name: value / total for name, value in numeric.items()}


def weighted_score(
    frame: pd.DataFrame,
    weights: Mapping[str, float],
    *,
    output_column: str = "overall_score",
) -> pd.DataFrame:
    """
    Calculate an explainable score from precomputed 0–100 components.

    Missing component scores are not silently filled. A row with a missing
    component used by a positive weight receives a missing overall score.
    """
    clean_weights = normalise_weights(weights)
    missing_columns = set(clean_weights).difference(frame.columns)
    if missing_columns:
        raise ValueError(
            f"Score columns not found: {sorted(missing_columns)}"
        )

    result = frame.copy()
    components = list(clean_weights)

    for column in components:
        numeric = pd.to_numeric(result[column], errors="coerce")
        invalid = numeric.dropna().loc[lambda values: ~values.between(0, 100)]
        if not invalid.empty:
            raise ValueError(f"{column} contains values outside 0–100.")
        result[column] = numeric

    result[output_column] = 0.0
    for column, weight in clean_weights.items():
        result[output_column] += result[column] * weight

    used = [
        column for column, weight in clean_weights.items() if weight > 0
    ]
    result.loc[result[used].isna().any(axis=1), output_column] = np.nan

    return result


def contribution_table(
    row: pd.Series,
    weights: Mapping[str, float],
) -> pd.DataFrame:
    """Explain one recommendation through weighted contributions."""
    clean_weights = normalise_weights(weights)
    records: list[dict[str, float | str]] = []

    for column, weight in clean_weights.items():
        score = float(row[column])
        records.append(
            {
                "component": column,
                "score": score,
                "weight": weight,
                "weighted_contribution": score * weight,
            }
        )

    return pd.DataFrame(records).sort_values(
        "weighted_contribution",
        ascending=False,
    )
