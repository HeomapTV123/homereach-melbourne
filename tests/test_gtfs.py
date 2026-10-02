import pandas as pd

from homereach.gtfs import gtfs_time_to_seconds


def test_gtfs_time_supports_after_midnight_values() -> None:
    assert gtfs_time_to_seconds("07:30:00") == 27_000
    assert gtfs_time_to_seconds("25:15:30") == 90_930
    assert pd.isna(gtfs_time_to_seconds("invalid"))
