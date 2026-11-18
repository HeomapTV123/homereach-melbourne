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

## Recovering the reported OpenJDK archive failure

On 18 November 2026, the user confirmed checkout `fc4a693` but environment creation failed while processing `openjdk-21.0.10-h56f2b75_22.conda`. The subsequent `EnvironmentLocationNotFound` means there was no valid `homereach-routing` environment to run. The truncated `InvalidArchiveError` does not establish whether the underlying problem was a damaged download, an extraction/path issue or another filesystem error. The displayed newer-Conda notice is separate from the archive exception.

That attempt also showed both conda-forge and defaults. The `nodefaults` correction addresses the observed channel configuration; it is not claimed to explain the archive failure. After pulling the correction, use one targeted retry in Anaconda Prompt / CMD.

First, quarantine only the exact cached archive named in the error, if it still exists:

```bat
set "HOMEREACH_FAILED_JDK=C:\Users\PhamDang\anaconda3\pkgs\openjdk-21.0.10-h56f2b75_22.conda"
if exist "%HOMEREACH_FAILED_JDK%" ren "%HOMEREACH_FAILED_JDK%" "openjdk-21.0.10-h56f2b75_22.conda.failed-%RANDOM%-%RANDOM%"
```

This preserves the failed archive under a different filename, leaves unpacked packages and existing environments in place, and prevents reuse of that file as the named package archive. If it is already absent, the conditional command does nothing. Do not remove the whole package-cache directory or an environment directory as part of this retry.

Capture the retry in a unique temporary log so a repeated error retains its full inner exception:

```bat
set "HOMEREACH_ROUTING_LOG=%TEMP%\homereach-routing-create-%RANDOM%-%RANDOM%.log"
conda env create -f environment-routing.yml --json > "%HOMEREACH_ROUTING_LOG%" 2>&1
type "%HOMEREACH_ROUTING_LOG%"
```

Output is redirected, so the terminal may remain quiet while Conda downloads and extracts packages. Wait for the prompt to return before displaying the log. [Conda's environment-creation command](https://docs.conda.io/projects/conda/en/stable/commands/env/create.html) documents the `--json` option.

If creation succeeds, run the prerequisite inventory command above. If it fails, inspect the full log before changing the retry strategy. In particular, an absent valid environment does not prove that no partial directory exists: report any prefix-already-exists message instead of deleting that directory blindly. A fresh cache location or Windows-specific path correction should be chosen from the complete exception, rather than assumed from `InvalidArchiveError` alone.

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
