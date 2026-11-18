# Routing runtime prerequisites

## Checkpoint and selected environment

The first development pair is recorded in [the station-access review](commute_station_access_review.md) and [its provisional reference manifest](../config/routing_development_references.json). The next step is a separate routing environment, followed by a tiny synthetic engine smoke test.

[`scripts/check_routing_runtime.py`](../scripts/check_routing_runtime.py) inventories the Python interpreter that actually runs it, installed distribution metadata, and the output of a bounded `java -version` subprocess. It uses only Python's standard library. It does not import r5py, JPype or GIS packages, start an embedded JVM, download the engine, load project datasets, or compute journeys.

The selected development baseline in [`environment-routing.yml`](../environment-routing.yml) is:

| Component | Selected version | Meaning |
| --- | --- | --- |
| Python | 3.12, 64-bit | Matches the project interpreter line. |
| r5py | 1.1.7 | Explicitly pinned for the first engine experiment. |
| OpenJDK | 21 | Selected Java baseline; upstream supports JDK 21 and later. |

The inventory reports other installed Python/r5py/Java versions as requiring separate review for this baseline, not as proof they are incompatible. The environment file is an input specification, not a lock of every resolved dependency. The actual Windows solve and native-library compatibility have not been demonstrated by Linux unit tests.

The channel list includes `nodefaults`, so creating this environment uses conda-forge without appending the user's configured default channels. This is scoped to this specification and does not change global Conda settings. [Conda's environment-file specification](https://conda.org/learn/specifications/exchange/environment-yml/#channels) documents this behavior.

## Run on Windows

For the machine with the confirmed C: storage failure, use [the D: recovery procedure](#windows-disk-space-recovery) below. The ordinary named-environment commands in this section assume sufficient space in Conda's default locations.

Use Anaconda Prompt / CMD from the project directory:

```bat
cd /d "D:\My project\homereach_melbourne"
git switch feat/commute-location-review
git pull --ff-only origin feat/commute-location-review
conda env list
```

If `homereach-routing` is absent, create it once:

```bat
conda env create -f environment-routing.yml
```

If the environment already exists, run the inventory first. There is no need to remove or rebuild it just to inspect its versions.

Then run:

```bat
conda run --no-capture-output -n homereach-routing python scripts/check_routing_runtime.py
```

For machine-readable output, the same command accepts `--json`. The checker reads distribution metadata for r5py, JPype1, GeoPandas, pandas, NumPy, Shapely, pyproj and rasterio. It checks the interpreter's architecture and consistency with `CONDA_PREFIX` when set. Java discovery uses the fixed executable name on absolute PATH entries, excludes the checkout/current directory, and runs only `-version` without a shell, with a ten-second timeout. Java option-injection environment variables are excluded from that subprocess.

| Result | Exit code | Interpretation |
| --- | --- | --- |
| `ROUTING RUNTIME PREREQUISITES: PASSED` | 0 | The selected version/metadata prerequisites were observed. Proceed to the controlled engine smoke test. |
| `ROUTING RUNTIME PREREQUISITES: BLOCKED` | 2 | A prerequisite is missing, unreadable or outside the selected baseline, or the interpreter/environment disagree. The report names it. |

Conda may append a generic failed-command message after exit code 2. Use the specific preceding inventory messages to diagnose the environment. This is separate from the existing routing-input preflight, which still reports the original street/location approval fields as unconfigured.

## Windows disk-space recovery

The full retry log supplied on 18 November 2026 from checkout `43acc1a` establishes the primary failure while extracting `C:\Users\PhamDang\anaconda3\pkgs\openjdk-21.0.10-h56f2b75_22.conda`:

```text
failed with error: [Errno 28] No space left on device
```

The later `AttributeError: 'InvalidArchiveError' object has no attribute 'dump_map'` occurs during JSON error reporting, after the storage failure. `EnvironmentLocationNotFound` follows because no valid routing environment was created. The earlier archive-renaming retry was diagnostic; repeated downloads into the same C: cache will not address insufficient storage. The `nodefaults` correction remains appropriate for channel selection but did not resolve disk capacity.

The recovery places the new environment, package cache and temporary extraction files together on D:, outside the repository. Existing `base`, `homereach` and `homereach-osm` installations remain at their current locations. Conda recommends putting the environment and cache on the same volume so files can be hard linked when supported; otherwise packages may need to be copied. See [custom environment/cache locations](https://docs.conda.io/projects/conda/en/latest/user-guide/configuration/custom-env-and-pkg-locations.html).

### Free cached archive space and check capacity

From the original Anaconda Prompt / CMD, before setting the D: cache override:

```bat
conda clean --tarballs --yes
"C:\Users\PhamDang\anaconda3\python.exe" -c "import shutil; print('C: free GiB:', round(shutil.disk_usage('C:/').free / 1024**3, 2)); print('D: free GiB:', round(shutil.disk_usage('D:/').free / 1024**3, 2))"
```

[`conda clean --tarballs`](https://docs.conda.io/projects/conda/en/26.1.x/commands/clean.html) removes downloaded package archives, not installed environment packages. It does not remove the previously renamed `.failed-*` archive or necessarily clear partial extractions. Avoid broad package-cache or environment-directory deletion.

Check the current numbers; earlier D: capacity measurements are not current evidence. About 10 GiB free on D: is a practical working margin for this attempt, not a measured package requirement. C: still needs headroom for Windows and small Conda/account metadata writes. If it remains effectively full after archive cleanup, resolve that storage shortage before proceeding.

### Configure a temporary child command prompt

Run `cmd /d` once. The following settings apply only to that child prompt; `exit` later returns to the original settings. This uses [CMD's inherited, process-local environment](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/cmd) without editing global Conda configuration.

```bat
cmd /d
```

In the child prompt, create the parent/cache/temp directories. If directory creation fails, inspect that error before continuing. Let Conda create the final environment directory itself.

```bat
if not exist "D:\homereach-conda\pkgs" mkdir "D:\homereach-conda\pkgs"
if not exist "D:\homereach-conda\tmp" mkdir "D:\homereach-conda\tmp"
if not exist "D:\homereach-conda\envs" mkdir "D:\homereach-conda\envs"

set "CONDA_PKGS_DIRS=D:\homereach-conda\pkgs"
set "TMPDIR=D:\homereach-conda\tmp"
set "TEMP=D:\homereach-conda\tmp"
set "TMP=D:\homereach-conda\tmp"
```

[`CONDA_PKGS_DIRS`](https://docs.conda.io/projects/conda/en/stable/user-guide/configuration/settings.html#pkgs-dirs-specify-package-directories) overrides package-cache locations. All three temporary variables are set because [Python/Conda checks TMPDIR, TEMP, then TMP](https://docs.conda.io/projects/conda/en/stable/user-guide/configuration/temp-files.html). Verify both destinations before downloading:

```bat
conda config --show pkgs_dirs
"C:\Users\PhamDang\anaconda3\python.exe" -c "import tempfile; print('Temporary directory:', tempfile.gettempdir())"
```

These should show `D:\homereach-conda\pkgs` and `D:\homereach-conda\tmp`, respectively.

### Create and inspect the explicit D: environment

Use ordinary console output for this retry because the observed JSON exception formatter failed. The optional log below captures all output on D:; wait for the command prompt before displaying it.

```bat
cd /d "D:\My project\homereach_melbourne"
set "HOMEREACH_ROUTING_LOG=D:\homereach-conda\tmp\create-routing-%RANDOM%-%RANDOM%.log"
conda env create --prefix "D:\homereach-conda\envs\homereach-routing" -f environment-routing.yml --yes > "%HOMEREACH_ROUTING_LOG%" 2>&1
type "%HOMEREACH_ROUTING_LOG%"
```

Both [`conda env create`](https://docs.conda.io/projects/conda/en/26.1.x/commands/env/create.html) and [`conda run`](https://docs.conda.io/projects/conda/en/stable/commands/run.html) accept an explicit prefix. After successful creation, use that same path:

```bat
conda run --no-capture-output --prefix "D:\homereach-conda\envs\homereach-routing" python scripts/check_routing_runtime.py
```

Keep using `--prefix` for this environment; `-n homereach-routing` may still resolve to the absent C: location because the new folder is outside the configured environment directories. The checker now uses the actual interpreter prefix in its retry hint when the prefix's final directory is `homereach-routing`. Runtime imports, the embedded JVM and actual journeys remain untested by this inventory.

If creation fails, retain the full log and inspect its specific error. An existing-prefix message does not authorize deleting the directory. After recording the outcome, run `exit` to return to the original prompt. The installed D: environment and log remain; the child's cache/temp overrides do not. Reapply those overrides for future installation/update operations that need D: storage.

## Why inventory precedes importing the engine

[r5py's installation guide](https://r5py.readthedocs.io/stable/user-guide/installation/installation.html) recommends a dedicated Conda/Mamba environment on Windows and specifies JDK 21 or later. The [conda-forge package index](https://anaconda.org/channels/conda-forge/packages/r5py/files) listed `r5py-1.1.7-pyhd8ed1ab_0.conda` when reviewed on 18 November 2026.

[r5py's configuration documentation](https://r5py.readthedocs.io/stable/user-guide/user-manual/configuration.html) describes an automatic compatible-R5 download when no custom classpath is supplied, first-run configuration templates, and a default JVM heap setting of 80% of memory. Therefore importing r5py is a separate execution step from reading its installed metadata.

The planned synthetic runner will use an explicitly identified local R5 JAR, validate its fingerprint before import, bound the JVM heap, and use temporary working/cache directories. That runner is not implemented or verified by this inventory checkpoint. It will write temporary engine artifacts; it must not claim the inventory's read-only behavior.

## Validation and next stage

The inventory's focused regression tests cover missing packages, unreadable metadata, version parsing, different baselines, environment mismatch, missing/failing/timed-out Java, executable discovery, and a fresh interpreter that denies imports of all routing/GIS packages. They run without installing r5py or launching an R5 engine.

At the 18 November 2026 implementation checkpoint, all 30 inventory cases passed and the full Linux suite passed **697 tests in 47.38 seconds**, with no skips. A real inventory of that test environment correctly reported missing r5py, JPype1 and rasterio while detecting OpenJDK 21.0.13. This exercises the blocked path; it does not verify the user's Windows routing environment or an R5 engine.

Run them in the existing test environment:

```bat
conda run --no-capture-output -n homereach python -m pytest -o "addopts=" -q tests/test_routing_runtime.py
```

The next engine test should build a tiny fictional connected street network and daytime GTFS fixture, verify a walking result, verify an actual transit segment, and exercise a no-service date. It establishes runtime/API behavior independently of Melbourne's station-access questions.

Before a Melbourne development itinerary, validate the complete GTFS timing/references and the chosen complete street-network input. In particular, [r5py's advanced-use documentation](https://r5py.readthedocs.io/stable/user-guide/user-manual/advanced-use.html) reports a limitation for GTFS times beyond `24:00:00`; the current small-table preflight does not evaluate that issue. Do not silently transform the frozen timetable to accommodate an engine.

The first explicitly labelled development itinerary will then provide evidence about coordinate linkage, walking access, paid barriers, platform access and timing. The provisional coordinates can support that investigation without treating those itinerary-dependent properties as already proved.
