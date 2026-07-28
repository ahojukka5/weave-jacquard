# Qualification

Jacquard uses one local qualification entry point:

```bash
bash scripts/qualify.sh MODE [OUTPUT_DIRECTORY]
```

`MODE` is `python`, `native`, or `full`.

## Evidence levels

### Python qualification

```bash
bash scripts/qualify.sh python
```

This mode:

- requires a clean tracked and untracked worktree;
- records the exact Git commit and Python environment;
- compiles every Python source file and runs Ruff;
- requires a working canonical Bubblewrap sandbox;
- runs the complete suite except tests marked `real_e2e`;
- includes real stdio MCP protocol tests;
- records coverage and JUnit XML;
- rejects every skipped test;
- requires exactly one copy of every protocol trace declared in
  `scripts/qualification-traces.json`.

The default output is `local-qualification/python`.

### Native qualification

```bash
WEAVEC_BIN=/absolute/path/to/weavec \
  bash scripts/qualify.sh native
```

This mode requires an executable final `weavec`. It runs tests marked
`real_e2e`, records the resolved compiler path, SHA-256 identity, and bounded
`--version` output, rejects every skip, and requires the native trace set and at
least one native `qualification-summary.json`.

A relative `WEAVEC_BIN` is resolved against the directory from which the runner
was invoked, not against the repository after the script changes directory.

The default output is `local-qualification/native`.

### Full qualification

```bash
WEAVEC_BIN=/absolute/path/to/weavec \
  bash scripts/qualify.sh full
```

This is the release-strength local gate. It runs the complete unfiltered suite
with coverage and requires both protocol and native trace contracts. A `full`
result is invalid when the compiler is absent, Bubblewrap isolation is
unavailable, any test is skipped, or any required trace is missing or duplicated.

The default output is `local-qualification/full`.

## Safe publication

Qualification never deletes or reuses the requested output directory. The output
must not already exist. A path inside the repository must be ignored by Git so it
cannot accidentally alter the commit being qualified.

Evidence is built in a same-filesystem staging directory. Failures remove only
runner-created temporary directories and publish no final evidence directory. A
successful run writes `qualification-complete.json` and `SHA256SUMS`, then moves
the completed staging directory into place without overwriting an output that
appeared concurrently.

This makes the presence of the final directory meaningful: partial compilation,
test, trace, or checksum output is not published as successful qualification.

## Isolated dependency environment

When the current Python cannot import the project test dependencies and `uv` is
available, the runner restarts itself through:

```text
uv run --isolated --extra dev
```

The selected environment kind, interpreter path, installed distribution inventory,
and Ruff identity are retained. Package inventory uses Python package metadata and
does not depend on `pip` being present in the isolated environment.

Bytecode caches, coverage state, and pytest temporary files are redirected outside
the worktree so qualification does not dirty the reviewed source.

## Retained evidence

Every successful mode writes:

```text
environment.txt
python-packages.txt
compileall.log
ruff.log
sandbox-capabilities.json
sandbox-binaries.json
pytest-command.txt
pytest.log
pytest-junit.xml
junit-summary.json
coverage.xml
qualification-traces.json
trace-index.json
traces/...
qualification-complete.json
SHA256SUMS
```

`environment.txt` records the tested commit, mode, final evidence path, platform,
Python and Ruff identities, and—where required—the compiler path, SHA-256, and
version. `sandbox-binaries.json` records the resolved Bubblewrap and `prlimit`
paths, sizes, and streaming SHA-256 identities alongside the capability report.

`qualification-complete.json` records `status = passed`, start and completion
instants, duration, mode, and Git SHA. `SHA256SUMS` covers every retained file
except itself.

## Skip policy

Qualification has no implicit skip allowance. Tests that require a capability
must either be excluded by the selected mode or have that capability available.
A test collected by the selected mode and then skipped invalidates the result.
This prevents a newly added optional dependency or missing runtime from silently
reducing coverage.

## Trace contract and bounds

`scripts/qualification-traces.json` is the machine-readable inventory of required
real-MCP evidence. The exact contract bytes are copied into the evidence directory
and their hash is bound into `trace-index.json`.

All discovered `*-trace.json` and `qualification-summary.json` files are copied
under `traces/` with their pytest temporary-directory structure preserved.
Required basenames must occur exactly once. Trace collection fails closed when it
encounters a symlink, more than 512 files, a file over 16 MiB, or aggregate trace
content over 128 MiB. The index records these effective limits, every retained
path, byte count, and SHA-256.

Additions, removals, and renames are qualification-contract changes and require
review together with the producing E2E test.

## Compatibility command

`scripts/qualify-immutable-revert.sh` remains as a compatibility wrapper:

- `focused` maps to unified `python` qualification;
- `full` maps to unified `full` qualification.

The wrapper does not retain a separate weaker evidence path. Its `full` mode
requires `WEAVEC_BIN` and the complete native qualification contract.
