-- Run after scripts/init_duckdb.py has created the views.

-- Check uniqueness at the intended rental-panel grain.
SELECT
    rental_area_name,
    quarter,
    property_type,
    COUNT(*) AS row_count
FROM rent_quarterly
GROUP BY ALL
HAVING COUNT(*) > 1;

-- Show the latest available period by property type.
SELECT
    property_type,
    MAX(quarter) AS latest_quarter
FROM rent_quarterly
GROUP BY property_type
ORDER BY property_type;

-- Compare annual rental growth using a four-quarter lag.
WITH rent_with_lag AS (
    SELECT
        rental_area_name,
        property_type,
        quarter,
        median_weekly_rent,
        LAG(median_weekly_rent, 4) OVER (
            PARTITION BY rental_area_name, property_type
            ORDER BY quarter
        ) AS rent_one_year_earlier
    FROM rent_quarterly
)
SELECT
    *,
    100.0 * (
        median_weekly_rent / NULLIF(rent_one_year_earlier, 0) - 1
    ) AS annual_growth_percent
FROM rent_with_lag
ORDER BY quarter DESC, annual_growth_percent DESC;
