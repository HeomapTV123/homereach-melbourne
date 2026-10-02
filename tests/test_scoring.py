import pandas as pd
import pytest

from homereach.scoring import (
    linear_limit_score,
    normalise_weights,
    weighted_score,
)


def test_linear_limit_score_has_clear_anchors() -> None:
    result = linear_limit_score(
        pd.Series([0, 45, 90]),
        preferred_limit=45,
    )
    assert result.tolist() == [100.0, 50.0, 0.0]


def test_weights_are_normalised() -> None:
    result = normalise_weights({"a": 2, "b": 1})
    assert result["a"] == pytest.approx(2 / 3)
    assert result["b"] == pytest.approx(1 / 3)


def test_weighted_score() -> None:
    data = pd.DataFrame(
        {
            "area": ["A"],
            "affordability_score": [80.0],
            "transport_score": [60.0],
        }
    )
    result = weighted_score(
        data,
        {
            "affordability_score": 0.75,
            "transport_score": 0.25,
        },
    )
    assert result.loc[0, "overall_score"] == pytest.approx(75.0)


def test_missing_score_is_not_silently_filled() -> None:
    data = pd.DataFrame(
        {
            "affordability_score": [80.0],
            "transport_score": [None],
        }
    )
    result = weighted_score(
        data,
        {
            "affordability_score": 0.5,
            "transport_score": 0.5,
        },
    )
    assert pd.isna(result.loc[0, "overall_score"])
