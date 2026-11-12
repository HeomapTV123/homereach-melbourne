# Main-branch quality review — 12 November 2026

## Evidence and scope

The maintainer supplied screenshots of all 11 open findings on SonarCloud's
`main` branch. This review uses their file/function locations and the source at
`c87857ed3ecb85377e124bed2d43373af69a3ef5`. Screenshot line numbers below describe
that original analysis; subsequent edits move lines.

Main's Security E / Reliability C gate conditions were already failing on
`f44474d`, before the forecasting merge. This does not establish that two
analyses contain identical findings. A successful pull-request gate evaluates
a different comparison from main's gate. See the official
[quality-gate explanation](https://docs.sonarsource.com/sonarqube-cloud/standards/managing-quality-gates/introduction-to-quality-gates).

| Finding group | Count | Reviewed response |
| --- | ---: | --- |
| Rental `fingerprint`, original line 42: path traversal via file content | 1 | Validate snapshot filenames across platforms and contain configuration-derived source paths before access; support explicit root-bound hashing. |
| Transport `export_outputs`, original line 283: path traversal via file content | 1 | Iterate the literal export-name inventories and check reference/destination containment, including symlinks, before comparison or writing. |
| CI install commands, original lines 25–27: source-distribution execution and unlocked dependencies | 6 | Install a complete hashed dependency lock from wheels; build and hash-install the local project with locked build tools and package-index access disabled. |
| Geography `read_inputs`, original line 122: filesystem oracle via file content | 1 | Validate filenames and contain paths before optional-file probes and upstream reads. |
| Notebook 02, original line 906: floating-point equality | 1 | Exact parser-fixture equality is intentional; recommend False positive for this occurrence, with the rationale below. Preserve the notebook. |
| Explorer test, original line 249: identical actual/expected expressions | 1 | Derive the expected cache key independently from fixture bytes using SHA-256. |

These are code changes and a documented review disposition. They are not a
claim that SonarCloud has already closed the findings. The notebook issue's
status needs to be changed in SonarCloud; no blanket exclusions or quality-gate
changes are part of this patch. The two separate analysis warnings visible in
the screenshots contain no details and are not represented as resolved here.

## Path boundaries

`homereach.io.paths.safe_filename` accepts one portable filename and rejects
parent components, separators, drive/stream syntax, reserved Windows device
names and malformed names. `contained_path` checks the resolved location under
the explicitly chosen project root, including symlinked directories, before
returning the lexical path used by reports and atomic replacements.

Rental and geography entry points validate configuration and source paths.
Geography checks optional inputs before testing their existence. Transport
checks references and destinations before comparisons, staging or writes in
both normal and check-only modes. Its original export-key inventory check
already rejected unexpected table names; iterating literal names now makes the
output path construction independent of data-derived mapping keys.

An explicit project root remains a local maintainer choice. Generic callers of
`fingerprint(path)` can still select an external file deliberately; callers
handling configuration-derived paths use containment and/or its `root=` check.
These controls do not provide a race-free sandbox against an actor concurrently
changing the filesystem. The existing single-build/concurrent-writer limits
remain applicable. No public web exploit is claimed from the screenshots.

## Independent explorer assertion

The old assertion compared `bundle_signature(...)` with another identical call.
A constant or incomplete cache key could satisfy that assertion. The corrected
test hashes the fixture manifest and every payload independently, in the
documented order, then compares that expected key with the function's result.
The test count is unchanged by this replacement.

## Notebook 02: exact parsing is intentional

The flagged assertion in code cell 12 is:

```python
assert parse_published_measure(pd.Series([600.5]), integer=False).iloc[0] == 600.5
```

This is a parser/type-conversion fixture. The value 600.5 equals 1201/2 and is
exactly representable in binary64. Evaluating only the pure parser with this
fictional input gives the same integer ratio and hexadecimal float value on
both sides: `(1201, 2)` and `0x1.2c40000000000p+9`.

No approximate arithmetic requires a tolerance. A tolerance would permit
unintended parser changes to the fixture value. The appropriate disposition is
**False positive for this specific assertion**. Suggested status comment:

> This assertion intentionally checks exact preservation of a parser fixture.
> The input 600.5 equals 1201/2 and is exactly representable in binary64. The
> operation is parsing and type conversion, not approximate arithmetic. Exact
> equality detects unintended value changes; introducing a tolerance would
> weaken that invariant.

The [official issue workflow](https://docs.sonarsource.com/sonarqube-cloud/managing-your-projects/issues/editing)
supports an Open → False positive transition with a status-change comment.
This review does not mark unrelated findings as false positives.

## CI dependency contract

`requirements.txt` continues to describe developer/runtime compatibility ranges.
`requirements-ci.in` combines those requirements with the CI installer and local
wheel build tools. `requirements-ci-py312-linux.lock` pins all 65 resolved
external packages and their SHA-256 hashes for CPython 3.12 on Ubuntu 24.04
x86_64. It is a CI platform lock, not a Windows environment replacement.

The workflow creates an isolated environment, installs the lock with
`--require-hashes --only-binary=:all:`, and builds the checked-out project using
the locked build tools with `--no-isolation` and package-index access disabled.
It hashes the resulting local wheel and installs it with dependency resolution
and index access disabled. `pip check` validates the installed dependencies.

The generated local-wheel hash verifies the built artifact at installation; it
is not independent provenance or proof of bit-for-bit reproducible wheel builds.
Building the project's own reviewed source is intentional. Deployment
requirements and the existing conda environment definitions are unchanged.

The lock was generated with **uv 0.13.6**. uv is used only to generate the lock;
it is not installed in CI or added as a runtime dependency. Regeneration command:

```bash
uv --no-config pip compile requirements-ci.in --python-version 3.12 --python-platform x86_64-manylinux_2_39 --only-binary=:all: --generate-hashes --default-index https://pypi.org/simple --output-file requirements-ci-py312-linux.lock
```

Regenerate when input requirements or build requirements change. Keep the
`setuptools`/`wheel` entries aligned with `pyproject.toml`. Existing locked
versions are retained by default; deliberate upgrades can use `--upgrade` or
`--upgrade-package`. Review the lock diff, repeat the clean install and run the
suite before accepting an update.

Primary references:

- [pip secure installations](https://pip.pypa.io/en/stable/topics/secure-installs/)
- [uv requirements locking](https://docs.astral.sh/uv/pip/compile/)
- [Python build command](https://build.pypa.io/en/stable/reference/cli.html)
- [Python 3.12 filesystem path semantics](https://docs.python.org/3.12/library/pathlib.html)

## Verification boundaries

Path regressions use temporary files, fictional metadata and controlled symlinks.
Existing transformation/export tests check normal behavior. The CI installation
was exercised in a fresh Python 3.12 environment, with exactly the locked
packages plus the local project and no broken dependency requirements. Final
commit test and analysis results belong in the associated PR/run records.

No real raw dataset or model evaluation is rerun by this review. Original
notebooks and outputs, source-snapshot configurations, frozen forecasting
protocols/calculations and all 11 packaged release files remain unchanged.
