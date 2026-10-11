# HomeReach — Reusable LGA geography pipeline

## What this update does

Refactors the proven matching and geographic-data export from
`04_lga_geography_and_rent_map.ipynb` into importable functions and one terminal
command. The reviewed scope remains 31 DFFH source-group metropolitan LGAs,
two-bedroom flats, the 2025Q3 rental snapshot and ABS 2025 GDA2020 boundaries.

It does not replace the notebook, train a model, download data, invent matches,
repair polygons, simplify boundaries, or change the Streamlit demonstration.

## Seven new files

- `config/lga_snapshot.json`: exact ZIP fingerprint, field layout, CRS, vintage,
  count expectations, exclusions and source references.
- `config/lga_name_aliases_2025.csv`: the three previously reviewed translations.
- `src/homereach/geography/__init__.py`: package marker.
- `src/homereach/geography/lga.py`: reusable validation, matching and exports.
- `scripts/build_lga_geography.py`: command-line entry point.
- `tests/test_lga_geography.py`: 69 synthetic test cases, including file round trips.
- `docs/geography_pipeline.md`: this guide.

Merge the ZIP's five top-level folders (`config`, `docs`, `scripts`, `src`,
`tests`) into the existing project root. Do not replace the project directory.
No original source file or notebook is included in this ZIP. No dependency-file
change is needed; the existing editable installation exposes the new package.

## Commands — Anaconda Prompt, from the project root

    cd /d "D:\My project\homereach_melbourne"
    conda activate homereach
    python -c "import sys; print(sys.executable)"
    python -m pytest -o "addopts=" -q

Expected total with the original 56 tests: **125 passed** (69 new cases).
The selected interpreter should be the existing `envs\homereach\python.exe`.
If a test fails, retain the error; do not delete the test or rebuild the environment.

First validate without writing files:

    python scripts/build_lga_geography.py --check-only

This also compares any existing notebook data exports. `--check-only` does not
write the registry, geographic files, or a fresh report. It prints
`GEOGRAPHY CHECK-ONLY PASSED` and `Files written: 0` on success.

Then build:

    python scripts/build_lga_geography.py --update-registry

Or rebuild data without modifying the registry:

    python scripts/build_lga_geography.py

The two flags `--check-only` and `--update-registry` are mutually exclusive.
The script finds its root from its own location; `--project-root` is available
for a deliberately separate project copy, not needed for normal use.

## Workflow and safeguards

1. Validate the rental CSV against the rental pipeline's recorded fingerprint.
2. Check all original rental metadata and complete quarter coverage.
3. Compare quarter-end timestamps in a common unit, preserving the pandas 2/3 fix.
4. Verify the original ABS archive fingerprint and six-member inventory.
5. Inspect the actual state records, exclude the three documented categories,
   and reject invalid, empty or missing council-area polygons.
6. Match exact names within Victoria; permit only the three explicit aliases.
7. Join by code, retaining every rental field and source coordinate.
8. Verify the original polygon for each code, not just the number of polygons.
9. Compare previous geographic data exports before replacing any file.
10. Stage files on the project's drive, reload them, compare them, then replace
    the derived outputs. Each replacement is atomic, not a multi-file database
    transaction. Do not run simultaneous builds or notebook exports.
11. Update the `boundaries` registry record only when explicitly requested.

There is no `--force` flag. A source fingerprint mismatch requires review, not
editing the expected hash to make it pass. A previous-export mismatch is useful
evidence: keep those existing files and investigate the differing value/shape.

## Explicit alias configuration

| Source label | ABS label | ABS code |
|---|---|---|
| Bayside | Bayside (Vic.) | 20910 |
| Kingston | Kingston (Vic.) | 23430 |
| Mornington Penin'a | Mornington Peninsula | 25340 |

The loader preserves these codes as strings. All columns are required, including
the review note. Missing, extra, duplicated, or contradictory aliases are
rejected. The code does not strip state suffixes globally or fuzzy-match names.
The 31-row derived crosswalk is still built and exported separately.

Name/code associations are reviewed matches. They do not establish that DFFH and
ABS use exactly identical geographic definitions or that 2025 shapes describe
all earlier years. This build deliberately maps 2025Q3 only.

## Output ownership

Four existing data products are rebuilt, with notebook parity checked first:

- `data/processed/geography/metro_lga_2025.gpkg`
- `data/interim/geography/lga_crosswalk_2025.csv`
- `data/interim/geography/latest_rent_by_lga_code.csv`
- `data/interim/geography/rent_map_2025q3.geojson`

A new, separate current-build manifest is written:

- `data/interim/geography/geography_pipeline_report.json`

The original HTML map, `geography_manifest.json` and `lga_geography_audit.md`
remain as records of the notebook run. Their older file hashes describe that
run; use `geography_pipeline_report.json` to validate the latest pipeline exports.
GeoPackage container bytes can change on export even when all attributes and
coordinates are identical. The checks compare data and shapes, not binary files.

The HTML is not regenerated by this command. Its rents/shapes remain the same
when the previous-export comparison passes. Use notebook 04 for map presentation
or changing display options. The notebook and script should not write outputs
at the same time.

## Geometry details

The native layer stays in EPSG:7844. It uses a mixed-geometry GeoPackage layer
with `geometry_type="Unknown"` and `promote_to_multi=False` to avoid converting
individual Polygon records to MultiPolygon records merely during export.
Coordinates are compared with zero tolerance for native read-backs. GeoJSON
uses EPSG:4326 via a real `to_crs()` transformation; the geometry check allows
only a 1e-10 degree numerical round-trip tolerance. Full GeoJSON properties are
compared, including all rental values and Excel source references.

## Registry update

`--update-registry` changes only the existing `dataset_id=boundaries` record and
appends provenance columns when needed. The status becomes `matched_validated`.
The record identifies the raw format as `Shapefile (ZIP)`, rather than confusing
that source format with the derived GeoPackage. It records the 2025 boundary
vintage separately from the 2025Q3 map reporting period and EPSG coordinate codes.

Existing notes, known-limitations text, acquisition dates and other dataset rows
are preserved. No download date or client-facing suitability conclusion is
invented. Transport and Census remain at their own statuses. A fingerprint-named
copy of the previous registry is saved under `data/interim/registry_backups/`.
The registry is validated before output replacement, then checked again for
concurrent edits before it is updated. Do not leave its CSV open in Excel.

## Testing and verification of this update

Preparation environment: Python 3.13.5, pandas 2.2.3, GeoPandas 1.1.2,
Pyogrio 0.12.1, Shapely 2.1.2 and PyProj 3.7.2 (Linux).

- All **69 new geography tests passed** without the official source files or network.
- Whole project test suite: **124 passed, 1 skipped**. The skipped case is the
  earlier rental pipeline's Parquet integration test because this preparation
  environment lacks pyarrow; it is not a skipped geography test.
- Actual uploaded ABS ZIP was read and validated with GDAL/Pyogrio.
- Actual rental workbook values were read without edits using artifact_tool and
  transformed using the existing tested rental parser to make the test CSV.
- Notebook 04's data construction/export was executed as an independent baseline;
  its display call was suppressed in the noninteractive test process.
- Every name/code mapping, native geometry, joined attribute and GeoJSON feature
  matched that baseline. The four existing data files passed pre-replacement checks.
- Both actual-data `--check-only` and `--update-registry` command paths passed.
- GeoPackage, GeoJSON (including a GDAL re-read) and CSV round trips passed.
- The HTML and original input files were unchanged.

This is not a verification of every possible Windows/library-version combination.
Run the tests in the user's existing `homereach` environment, where the earlier
56 tests including Parquet already passed. Nothing here requires installing a new
package. A skipped test is not counted as a pass.

## Read these functions first

`build_crosswalk(source, lookup, aliases)` returns the reviewed 31-row association
table. `join_boundaries(latest, councils, aliases)` returns the native polygons,
crosswalk and joined map table. `verify_map(...)` checks all original rents and
ensures each LGA code received its own original polygon. `export_geography(...)`
compares existing files, stages and reads back new files, and records provenance.

A map with 31 features can still be wrong if two shapes are swapped. That is why
both association checks and exact per-code geometry checks matter.

## Technical references

- https://geopandas.org/en/stable/docs/user_guide/io.html
- https://geopandas.org/en/stable/docs/user_guide/mergingdata.html
- https://geopandas.org/en/stable/docs/reference/api/geopandas.GeoDataFrame.to_crs.html
- https://shapely.readthedocs.io/en/stable/reference/shapely.equals_exact.html
- https://pyogrio.readthedocs.io/en/latest/api.html#pyogrio.write_dataframe
- https://docs.pytest.org/en/stable/how-to/tmp_path.html
- https://docs.pytest.org/en/stable/how-to/parametrize.html

## Next milestone

After local tests and this build pass, commit the new code/configuration/tests,
this guide and the updated registry. Keep raw and processed files local under the
existing ignore rules. Do not change project scope or mark real recommendations
as completed. Next is the separate GTFS source audit and scheduled-transport
feature pipeline; the reviewed LGA geometry will support stop-to-area matching.
