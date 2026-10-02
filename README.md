# HomeReach Melbourne

An explainable geospatial data-science project for comparing Melbourne areas
by rental affordability, public-transport access, commute time, historical
environmental conditions, and expected rent pressure.

This starter repository is intentionally staged:

1. Run a working Streamlit prototype with synthetic sample data.
2. Audit and clean the official rental workbook.
3. Join official geographic boundaries.
4. Engineer public-transport features from GTFS.
5. Replace sample component scores with calculated features.
6. Add time-aware rent forecasting.
7. Add historical heat and vegetation layers.
8. Add network-based commute times as an advanced extension.

## Important modelling language

Use **area**, **DFFH rental area**, or **LGA** until the geography is
verified. Some published rental-market labels may combine more than one
suburb, so do not automatically describe every row as a single suburb.

## Quick start with Conda

```powershell
cd homereach_melbourne_starter
conda env create -f environment.yml
conda activate homereach
python -m pip install -e .
pytest
streamlit run app/Home.py
```

The first app run uses `data/sample/candidate_areas.csv`, which contains
synthetic demonstration data. It is labelled in the interface and must not
be presented as a real Melbourne result.

## JupyterLab

```powershell
jupyter lab
```

Open:

```text
notebooks/01_data_audit.ipynb
```

Place the official rental workbook inside:

```text
data/raw/rent/
```

Rename it to `dffh_rental_time_series.xlsx`, or edit the configured path.

## Repository layout

```text
app/                         Streamlit interface
config/                      Project settings
data/raw/                    Original, unchanged source files
data/interim/                Cleaned but not final data
data/processed/              Analysis-ready tables
data/sample/                 Synthetic data for testing the app
docs/                        Data registry and documentation
notebooks/                   Exploration and learning
scripts/                     Repeatable command-line jobs
sql/                         DuckDB views and analytical SQL
src/homereach/               Reusable Python package
tests/                       Automated tests
```

## Core analytical grain

The recommended rental table grain is:

```text
one row = one rental area × one quarter × one property type
```

The key should therefore be unique:

```text
(rental_area_name, quarter, property_type)
```

## Recommended release order

### Release 1 — Rental map

- Clean quarterly rental data.
- Join LGA geography first.
- Produce one interactive choropleth.
- Add a data-quality report.

### Release 2 — Transport access

- Load metropolitan GTFS.
- Calculate weekday and peak-period departures.
- Aggregate service measures to area geography.
- Add accessibility indicators where available.

### Release 3 — Explainable recommendation app

- Add budget, commute and preference controls.
- Calculate transparent component scores.
- Show the contribution of each component.
- Explain trade-offs instead of claiming one area is universally “best”.

### Release 4 — Forecasting and advanced geography

- Build a seasonal-naive baseline.
- Compare Ridge regression and a tree model.
- Use chronological validation.
- Create a reviewed crosswalk for grouped rental areas.
- Add historical heat/vegetation and routing only after the MVP works.

## Definition of done

See `docs/definition_of_done.md`.

## Data sources

See `docs/data_registry.csv`. Download official source files manually and
keep the originals unchanged in `data/raw/`.
