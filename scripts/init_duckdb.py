from __future__ import annotations

from pathlib import Path

import duckdb

DATABASE = Path("data/processed/homereach.duckdb")
PROCESSED = Path("data/processed")


def main() -> None:
    DATABASE.parent.mkdir(parents=True, exist_ok=True)

    with duckdb.connect(str(DATABASE)) as connection:
        rent_path = PROCESSED / "rent_quarterly.parquet"
        features_path = PROCESSED / "area_features.parquet"

        if rent_path.exists():
            connection.execute(
                """
                CREATE OR REPLACE VIEW rent_quarterly AS
                SELECT * FROM read_parquet(?)
                """,
                [str(rent_path)],
            )
            print(f"Created rent_quarterly view from {rent_path}")
        else:
            print(f"Skipped missing file: {rent_path}")

        if features_path.exists():
            connection.execute(
                """
                CREATE OR REPLACE VIEW area_features AS
                SELECT * FROM read_parquet(?)
                """,
                [str(features_path)],
            )
            print(f"Created area_features view from {features_path}")
        else:
            print(f"Skipped missing file: {features_path}")

    print(f"DuckDB ready at {DATABASE}")


if __name__ == "__main__":
    main()
