# HomeReach — portable release and Streamlit Community Cloud

## Goal and current scope

Make the working real-data explorer runnable from a GitHub checkout without raw
GTFS, Excel, shapefiles, interim data, local upstream reports or Conda. This is a
frozen release of the reviewed data, not an automatic refresh service.

The local app remains `app/Explore.py` and still requires the existing local
manifest/report checks. The hosted entry point is `deploy/streamlit_app.py`.
The synthetic demo remains `app/Home.py`; neither real-data app loads it.

## Files in this update

New files:
- `src/homereach/explorer/release.py`: allowlisted packager and standalone reader.
- `src/homereach/explorer/release_ui.py`: hosted navigation and attribution page;
  reuses existing comparison, details and map renderers.
- `scripts/package_explorer.py`: read-only preflight or package command.
- `scripts/verify_explorer_release.py`: no-upstream standalone verifier.
- `deploy/streamlit_app.py`: deployment entry point, imports `src` explicitly.
- `deploy/requirements.txt`: serving dependencies only.
- `deploy/.gitattributes`: preserves release file bytes across Windows/Linux.
- `deploy/.gitignore`: staging directories, Python caches and secrets excluded.
- `deploy/DATA_SOURCES.md`: attribution, processing descriptions and licence evidence.
- `tests/test_explorer_release.py`: 41 data/package tests using fictional data.
- `tests/test_explorer_release_ui.py`: 3 Streamlit AppTest smoke tests.
- `docs/explorer_deployment.md`: this guide.

One existing file changes: `src/homereach/explorer/bundle.py`. Its GeoPandas and
PyProj imports move inside the functions that BUILD geographic data. Validation,
source-report checks, public function names, schemas and calculations do not
change. The release therefore does not install GIS build tools just to display
existing GeoJSON. Root requirements, environment, .gitignore and CI stay unchanged.

## Copy safely

Merge the ZIP's `deploy`, `docs`, `scripts`, `src` and `tests` directories into the
existing HomeReach project. Allow replacement of the supplied `bundle.py` after
preserving any personal edits. Do not delete an entire project directory. No
raw or generated data is supplied by the update ZIP. The release must be built
from YOUR validated local explorer bundle.

## Local checks

Run in Anaconda Prompt:

```bat
cd /d "D:\My project\homereach_melbourne"
conda activate homereach
python -m pytest -o "addopts=" -q
python scripts/package_explorer.py --check-only
python scripts/package_explorer.py
python scripts/verify_explorer_release.py
```

Expected full suite with all required packages: **352 passed** (308 existing +
41 release-data cases + 3 release-UI cases). Do not count a skipped test as a pass.
A Git integration test can skip on a machine without Git; this project has Git.

The package preflight checks all nine data files through the existing local
bundle loader and preserves its upstream-report checks. Check-only writes no
release directory. The full command stages an allowlisted copy, reads it back
and compares every table and geometry before publishing the folder. An initial
release writes 11 files. An identical rerun writes none and keeps its timestamp.
A changed existing release fails closed; do not edit hashes or delete it to
bypass a mismatch. A later data update needs a reviewed release change.

## Release inventory

Only this deliberate release subset may be committed as data:

```text
deploy/data/
  am_lga_category_comparison.csv
  lga_transport_comparison.csv
  rent_transport_comparison.csv
  am_stop_denominator_comparison.csv
  study_area_reconciliation.csv
  source_periods.csv
  rental_history.csv
  lga_service_categories.csv
  lga_boundaries_2025.geojson
  source_attribution.json
  release_manifest.json
```

These are eight CSVs, one map geometry, attribution and a manifest. The inspected
source-derived data payload is about 4.56 MiB; actual printed size is authoritative.
The release includes 31 comparison rows, 3,286 history rows, 248 service-category
rows and 31 geographic features. Dates and all original rental references stay
unchanged. The remaining CSVs carry supporting area-level summaries and periods.

No raw ZIP/workbook, stop/trip identifiers, user home paths, Conda installation,
passwords, tokens, secret files, Python pickle, generated HTML or notebook output
is copied. Only selected fields from the local manifest are published. The
private input-hash map and upstream report paths are not copied. Strict byte
checksums provide integrity relative to this manifest, not authenticity against
a malicious author who replaces both data and manifest.

The hosting reader checks only this release; it cannot check live upstream
files on the user's computer. Packaging checked that lineage before freezing it.

## Why .gitattributes matters

The project previously reported LF/CRLF conversion warnings. The release uses
byte-specific SHA-256 checks. `deploy/.gitattributes` contains `data/** -text`,
which disables Git text conversion only for these packaged CSV/JSON/GeoJSON
files. Without it, a Windows/Linux checkout could change bytes while retaining
the same logical data. Do not remove that file or modify global Git settings.
Other source-code files keep their existing line-ending behaviour.

## Preview the portable app

Keep the previous local app separate and use a different port:

```bat
python -m streamlit run deploy/streamlit_app.py --server.port 8503
```

Open the Local URL, normally `http://localhost:8503`. Sidebar must say **FROZEN
RELEASE**, not LOCAL BUILD. Test comparison filters, an empty filter, downloads,
Melbourne area details, the map and source/licence information. Defaults and data
must match the existing app: 31 areas, rental range $400–$730, Melbourne rent
$730/week and distinct AM trips 1,633. These are historical snapshot values.

A missing or altered release shows an error, never a synthetic fallback. No
server command attempts to rebuild datasets or contact publishers. Online map
tiles remain opt-in; enabling them requests data from the map provider. Streamlit
hosting itself may make its own platform/telemetry requests; this is not a claim
that every browser or platform connection is offline.

## Save only after checks pass

Review the changes and source attribution before publishing. A public repository
makes the selected release files public too. Keep raw/processed pipeline data
ignored; do not force-add it. `deploy/data` is an intentional exception consisting
only of the listed release subset, not a relaxation of the root ignore policy.

```bat
git add deploy scripts/package_explorer.py scripts/verify_explorer_release.py
git add src/homereach/explorer/bundle.py src/homereach/explorer/release.py src/homereach/explorer/release_ui.py
git add tests/test_explorer_release.py tests/test_explorer_release_ui.py docs/explorer_deployment.md
git --no-pager diff --cached --stat
git status
```

Confirm that no raw source archives, secrets or unrelated notebook changes are
staged. Check the data's attribute policy, then commit:

```bat
git check-attr text -- deploy/data/rent_transport_comparison.csv
git commit -m "feat: package portable real-data explorer release"
git push
```

The attribute result should end with `text: unset`. Normal push only; no amend or
force push. Existing CI collects the 44 new tests; a successful full test log should
show 352 cases. Those tests are synthetic; actual release verification is a separate
local command. The current workflow does not automatically rebuild government data.

## Streamlit Community Cloud setup (after local checks and push)

1. Sign into Streamlit Community Cloud with GitHub and create an app from an
   existing repository. Authorise repository access only as required by its UI.
2. Repository: `HeomapTV123/homereach-melbourne`.
3. Branch: `main`.
4. Main file path: `deploy/streamlit_app.py` — NOT `app/Home.py` or `app/Explore.py`.
5. Under Advanced settings choose Python **3.12**. This app needs no data API keys
   or secrets; leave the secrets field empty. Never commit personal credentials.
6. Deploy and inspect the server logs and all four browser pages. The platform
   assigns the URL; do not invent a public link before it exists.

Community Cloud checks dependency files beside the entry point before checking
repository-root files. `deploy/requirements.txt` therefore avoids installing the
root Conda/build environment. Its direct runtime dependencies are Streamlit,
pandas, NumPy, Plotly, Shapely and packaging. The source package is found from the
entry point's explicit `src` path; no editable install or OS GIS packages are
needed at runtime.

Version ranges are bounded compatibility ranges, not a lockfile. Local and cloud
patch versions can differ. Once the first hosted build succeeds, record its
versions for reproducibility rather than blindly changing the working Conda env.
The hosting version has not been deployed or tested by preparing this patch.

## Troubleshooting

- Release missing: run `python scripts/package_explorer.py` locally. Verify that
  all 11 generated release files were intentionally committed and pushed.
- Hash mismatch only after checkout: verify `deploy/.gitattributes`; never replace
  a stored hash merely to suppress an error. Compare actual bytes and Git diff.
- Missing module on the host: confirm the entry point and dependency file path.
  Do not recreate the local environment or upload site-packages.
- Blank interactive map: test the same table below it, inspect browser WebGL and
  use the existing map checks. The default white background is intentional;
  missing coloured shapes are not.
- Changed upstream reports locally: use the normal explorer build to review the
  updated local inputs. Public releases are intentionally frozen; they do not
  change just because an upstream manifest was regenerated.

## Verification performed while preparing this update

- Python 3.13.5 / pandas 2.2.3 in the preparation environment.
- All 41 new data/package tests passed, including the Git line-ending test.
- Full available suite: 338 passed, 3 skipped. Skip reasons: the pre-existing
  rental Parquet case lacks pyarrow, and the existing/new Streamlit UI modules
  lack Streamlit. They were NOT counted as passed.
- The three new UI cases and live Streamlit server were not executed here because
  Streamlit was unavailable and package installation had no network access.
- Actual uploaded workbook values were read with artifact_tool and passed through
  the validated rental transformation; the CSV and source comparisons passed.
  No new rental Parquet file was produced in this test environment.
- Geography, transport and explorer inputs were reconstructed from the uploaded
  sources in an isolated project. Absent earlier notebook-reference outputs were
  explicitly not claimed as compared during that reconstruction.
- Release packaging, independent loading and byte-stable reruns passed using that
  reconstructed real-data explorer. All nine payload data files matched exactly.
- An isolated copy containing no raw files or upstream reports loaded correctly.
- Existing local-source checks still fail when a source report changes; they were
  not disabled. Python files compile. No remote files were written or app deployed.

## Official references

- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/file-organization
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
- https://docs.streamlit.io/develop/api-reference/app-testing
- https://git-scm.com/docs/gitattributes
- Dataset-specific attribution sources are recorded in `deploy/DATA_SOURCES.md`.
