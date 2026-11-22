# Routing runtime prerequisites

## Checkpoint and selected environment

The first development pair is recorded in [the station-access review](commute_station_access_review.md) and [its provisional reference manifest](../config/routing_development_references.json). The separate Windows environment passes the prerequisite inventory and the synthetic timing/integration checks with the scoped leg-copy adapter. [The supplied Windows timing checkpoint](commute_routing_smoke_test.md#verified-windows-timing-checkpoint) is complete. The subsequent [walking-geometry baseline](commute_routing_geometry_check.md) fails on both Linux and Windows. An explicit [experimental walking correction](commute_routing_walking_correction.md) now passes all enabled fixture checks on Linux and in the maintainer's supplied Windows run at `219f326`. That Windows console evidence was supplied on 21 November 2026 and uses the existing environment and reviewed JAR.

[`scripts/check_routing_runtime.py`](../scripts/check_routing_runtime.py) inventories the Python interpreter that actually runs it, installed distribution metadata, and the output of a bounded `java -version` subprocess. It uses only Python's standard library. It does not import r5py, JPype or GIS packages, start an embedded JVM, download the engine, load project datasets, or compute journeys.

The selected development baseline in [`environment-routing.yml`](../environment-routing.yml) is:

| Component | Selected version | Meaning |
| --- | --- | --- |
| Python | 3.12, 64-bit | Matches the project interpreter line. |
| r5py | 1.1.7 | Explicitly pinned for the first engine experiment. |
| OpenJDK | 21 | Selected Java baseline; upstream supports JDK 21 and later. |

The inventory reports other installed Python/r5py/Java versions as requiring separate review for this baseline, not as proof they are incompatible. The environment file is an input specification, not a lock of every resolved dependency. The actual Windows solve and native-library compatibility have not been demonstrated by Linux unit tests.

The channel list includes `nodefaults`, so creating this environment uses conda-forge without appending the user's configured default channels. This is scoped to this specification and does not change global Conda settings. [Conda's environment-file specification](https://conda.org/learn/specifications/exchange/environment-yml/#channels) documents this behavior.

## Observed Windows checkpoint — 18 November 2026

The maintainer supplied a completed environment-creation log and a successful prerequisite inventory from checkout `dcf7c2e`. The selected environment is `D:\homereach-conda\envs\homereach-routing`; the reported Python and Java executables are inside that prefix.

| Observed component | Reported version |
| --- | --- |
| Python | 3.12.16, 64-bit |
| r5py | 1.1.7 |
| JPype1 | 1.7.1 |
| GeoPandas | 1.2.0 |
| pandas | 3.0.3 |
| NumPy | 2.3.5 |
| Shapely | 2.2.0 |
| pyproj | 3.8.0 |
| rasterio | 1.5.2 |
| Java | OpenJDK 21.0.10, Zulu21.48+17-CA, build 21.0.10+7-LTS |

The checker reported `ROUTING RUNTIME PREREQUISITES: PASSED`, with zero project datasets read, project files written or journeys computed. This inventory verifies the reported interpreter, package metadata and Java version probe; package/native-library imports, the embedded JVM, network loading and routing belong to [the separate synthetic smoke test](commute_routing_smoke_test.md).

The maintainer then supplied the Windows smoke-test output from checkout `c03cb4a`. The embedded JVM started and all three synthetic queries ran, but the returned 60 transit alternatives contained 23 chronology overlaps and 59 bus-wait mismatches. The command exited with code 1, removed its temporary workspace, read no real project datasets and computed no Melbourne journeys. This matches the preserved Linux upstream result.

At checkout `73543a8`, the maintainer supplied a successful Windows run with `--isolate-itinerary-legs`: 60 transit alternatives, zero timeline/sequence/egress-padding failure counts, 180 leg snapshots, the original method restored, three completed queries, successful temporary cleanup and exit code 0. The [recorded checkpoint](evidence/routing_smoke_windows_checkpoint_2026-11-18.json) identifies these observations as supplied terminal evidence; no complete Windows raw-leg JSON report was provided. This confirms the synthetic timing/integration checkpoint on the installed environment.

The later Linux run with the additional `--check-walking-geometry` flag fails its independent walking-accuracy assertions while retaining zero timing failures. The maintainer's [Windows run at `1be659f`](evidence/routing_geometry_windows_checkpoint_2026-11-18.json) confirms the same result: 121 walking endpoint, geometry-length and off-reference-path failures, 61 reported-reference-distance failures, successful cleanup and exit code 1. [The investigation](commute_routing_geometry_check.md) records the raw Linux comparisons and native reverse-search state evidence.

Adding the new `--correct-walking-paths` mode passes the unchanged fixture on Linux: 53 returned alternatives, 107 walking legs, zero enabled timing/geometry/duration failures and successful restoration and cleanup. The [new guide and evidence](commute_routing_walking_correction.md) separate that bounded experiment from the baseline failure. It requires the already embedded Java 21 compiler, preserves the installed package and JAR, and rejects networks outside the reviewed fixture.

The [corrected Windows result at `219f326`](evidence/routing_walk_correction_windows_checkpoint_2026-11-21.json), supplied on 21 November 2026, reports those same diagnostic counts and displayed distances, 159 snapshots, restoration of all scopes, three completed queries, successful cleanup and exit code 0. It also reports r5py 1.1.7, the verified R5 `v7.5.1-r5py` JAR, a 1 GiB heap limit and one Python routing job. The console does not supply a fresh Java version, helper-class fingerprint, full raw-leg report or execution timestamp. This checkpoint verifies the combined fixture command on the Windows environment; exact raw-row equivalence, Melbourne input compatibility, access and actual journey timing remain separate checks.

The same supplied session reported 8.98 GiB free on C: and 238.34 GiB on D: after archive cleanup, and `tempfile.gettempdir()` returned `D:\homereach-conda\tmp`. However, `conda config --show pkgs_dirs` still listed three C: cache locations after the D: override command. **The environment and temporary-directory relocation were observed; package-cache relocation was not confirmed.** The cause of that discrepancy is unresolved. Preserve the working environment; use the scoped checks below before future package installations or updates.

The creation log's `Channels` section listed only conda-forge. A later informational notice mentioned `defaults`; that notice alone does not establish which channels supplied installed packages. This checkpoint did not inspect every package's channel provenance or produce a complete environment lock.

## Run on Windows

The maintainer's D: environment has already been created successfully. Inspect it with the explicit prefix; do not repeat creation:

```bat
conda run --no-capture-output --prefix "D:\homereach-conda\envs\homereach-routing" python scripts/check_routing_runtime.py
```

The [D: recovery procedure](#windows-disk-space-recovery) below records the storage setup and the additional cache-verification requirement. The ordinary named-environment commands in this section are for another setup with sufficient space in Conda's default locations.

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

This procedure is intended to place the new environment, package cache and temporary extraction files together on D:, outside the repository. The observed checkpoint above confirms only the environment and temporary locations; cache verification must succeed before future package operations. Existing `base`, `homereach` and `homereach-osm` installations remain at their current locations. Conda recommends putting the environment and cache on the same volume so files can be hard linked when supported; otherwise packages may need to be copied. See [custom environment/cache locations](https://docs.conda.io/projects/conda/en/latest/user-guide/configuration/custom-env-and-pkg-locations.html).

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

[`CONDA_PKGS_DIRS`](https://docs.conda.io/projects/conda/en/stable/user-guide/configuration/settings.html#pkgs-dirs-specify-package-directories) sets package-cache configuration; verify the effective list rather than assuming that the command took effect. All three temporary variables are set because [Python/Conda checks TMPDIR, TEMP, then TMP](https://docs.conda.io/projects/conda/en/stable/user-guide/configuration/temp-files.html). Verify both destinations before downloading:

```bat
conda config --show pkgs_dirs
"C:\Users\PhamDang\anaconda3\python.exe" -c "import tempfile; print('Temporary directory:', tempfile.gettempdir())"
```

The first configured cache should be `D:\homereach-conda\pkgs`, and the temporary directory should be `D:\homereach-conda\tmp`. **If D: is absent from the cache list, C: remains first, or the temporary path is wrong, stop before starting another package operation.** A successful environment creation does not retrospectively prove that its cache used D:.

For that mismatch, run only these narrowly scoped, read-only diagnostics in the same child prompt after setting the variables:

```bat
where conda
"C:\Users\PhamDang\anaconda3\python.exe" -c "import os,sys,conda; from conda.base.context import context; print('Python:',sys.executable); print('Conda:',conda.__version__); print('CONDA_PKGS_DIRS:',repr(os.environ.get('CONDA_PKGS_DIRS'))); print('Effective pkgs_dirs:',list(context.pkgs_dirs))"
"C:\Users\PhamDang\anaconda3\python.exe" -m conda config --show pkgs_dirs
```

Compare these with the ordinary `conda config --show pkgs_dirs` output. They inspect command discovery, the one relevant inherited variable and Conda's resolved cache list without printing unrelated configuration or credentials. In [Conda 26.1.1's implementation](https://github.com/conda/conda/blob/26.1.1/conda/cli/main_config.py), `--show` reads the effective context; [the cache property](https://github.com/conda/conda/blob/26.1.1/conda/base/context.py) returns the standard C: locations when no configured cache list is present. The supplied output is insufficient to attribute the mismatch to a wrapper, configuration or another cause. Diagnose it before changing configuration; a working routing environment does not need rebuilding for this check.

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

The separate [synthetic runner](../scripts/run_routing_smoke_test.py) uses an explicitly identified local R5 JAR, validates its fingerprint before import, bounds the JVM heap, and uses temporary working/cache directories. It writes temporary engine artifacts and has a different contract from this inventory. Its unmodified upstream execution failed detailed-itinerary chronology checks on both Linux and Windows. The explicit leg-isolation adapter passed the timing checks on both platforms with the same fixture; see [its scope, evidence and Windows command](commute_routing_smoke_test.md). The adapter makes a temporary in-memory change in the fresh worker and does not alter the installed environment. The additional geometry baseline fails on both platforms. The newer fixed-fixture walking correction passes timing, geometry, distance and duration checks on Linux and in the supplied Windows console evidence, with its own guards and temporary helper.

## Validation and next stage

The inventory's focused regression tests cover missing packages, unreadable metadata, version parsing, different baselines, environment mismatch, missing/failing/timed-out Java, executable discovery, and a fresh interpreter that denies imports of all routing/GIS packages. They run without installing r5py or launching an R5 engine.

At the initial 18 November 2026 implementation checkpoint (`fc4a693`), all 30 inventory cases passed and the full Linux suite passed **697 tests in 47.38 seconds**, with no skips. A real inventory of that test environment correctly reported missing r5py, JPype1 and rasterio while detecting OpenJDK 21.0.13. That initial run exercises the blocked path. The later successful Windows inventory is recorded above. The subsequent engine experiments have separate evidence for the upstream failure, the scoped adapter's Linux and Windows timing passes, the expanded geometry failure on both platforms, and the fixed-fixture walking correction's Linux and supplied Windows passes. The historical test count does not describe those later changes.

Run them in the existing test environment:

```bat
conda run --no-capture-output -n homereach python -m pytest -o "addopts=" -q tests/test_routing_runtime.py
```

The engine diagnostic builds a tiny fictional connected street network and daytime GTFS fixture, checks a walking result and actual transit segments, and exercises a no-service date. Its successive checkpoints are documented in [the smoke-test guide and evidence](commute_routing_smoke_test.md). The timing-only command with `--isolate-itinerary-legs` remains valid. The supplied Windows run with `--check-walking-geometry` completed the expected failing baseline. The later successful Windows command adds `--correct-walking-paths` while retaining both preceding flags; see [the recorded Windows command](commute_routing_walking_correction.md#verified-windows-command). It uses the same environment and JAR.

The independent returned-leg checks now pass in the bounded Linux and supplied Windows experiments, but the fixed-fixture index adapter and limited origin wrapper are not a production routing integration. The separate [departure-sampling investigation](commute_routing_departure_sampling.md) explains the 60-to-53 alternative change through a target-arrival cutoff retained across samples. Resetting that cutoff is a diagnostic experiment, not a shipped general repair or proof of complete route enumeration. Before a Melbourne development itinerary, establish an appropriate integration beyond that fixture, validate complete GTFS timing/references and the chosen complete street-network input, and review routes and transfers. In particular, [r5py's advanced-use documentation](https://r5py.readthedocs.io/stable/user-guide/user-manual/advanced-use.html) reports a limitation for GTFS times beyond `24:00:00`; the current small-table preflight does not evaluate that issue. Do not silently transform the frozen timetable to accommodate an engine.

The [complete GTFS timetable audit](commute_gtfs_timetable_audit.md) supplies a separate read-only source check. The supplied Windows JSON confirms a pass for 11,847,183 source rows and 1,311,746 active rows, unchanged protected inputs and successful cleanup. It uses the existing `homereach` environment, an external temporary directory and no JVM. There are 8,430 active rows at or beyond `24:00:00`; the maximum over all source rows is `32:47:00`. The [service-day compatibility experiment](commute_routing_service_day_check.md) now checks these boundary behaviours on a fictional Melbourne-timezone timetable with the pinned engine. Its evidence is separate from source validation and real Melbourne routing.

The first explicitly labelled development itinerary will then provide evidence about coordinate linkage, walking access, paid barriers, platform access and timing. The provisional coordinates can support that investigation without treating those itinerary-dependent properties as already proved.
