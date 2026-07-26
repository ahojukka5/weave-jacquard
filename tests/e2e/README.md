# Real MCP qualification

These tests launch the actual `weave-mcp` stdio process with the official MCP
Python client. They do not import and call MCP tool functions directly.

## Protocol qualification

```bash
python -m pytest -m real_mcp tests/e2e
```

The always-runnable qualification suite verifies:

- MCP session initialization and production tool discovery;
- construction of a complete constant-returning program through atomic tools;
- canonical source rendering and immutable branch history;
- rejected cyclic mutations without branch advancement, followed by valid repair;
- independent agent branches merged with stable node identities preserved;
- revision-pinned multi-document targets and exact additional-source order;
- historical target and source reads after later branch revisions.

Each qualification module writes a complete JSON tool-call trace to the pytest
temporary directory.

Run only the minimal construction flow:

```bash
python -m pytest -m real_mcp tests/e2e/test_real_mcp.py
```

Run only branch, repair, merge, and target workflows:

```bash
python -m pytest -m real_mcp tests/e2e/test_real_mcp_workflows.py
```

## Compiler-backed native qualification

```bash
WEAVEC_BIN=/absolute/path/to/weavec \
  python -m pytest -m real_e2e tests/e2e/test_real_mcp.py
```

This additionally validates the program through `weavec --frontend`, builds it
through `weavec build`, verifies the stored build through `build_get`, executes
the returned native binary, and requires exit status 42.

The compiler-backed test skips when `WEAVEC_BIN` is unset or not executable.
The test currently executes native artifacts only on POSIX systems.

## Packaged compiler qualification in CI

`.github/workflows/native-e2e.yml` resolves the immutable `weavec v0.3.0`
release metadata, selects the unique Linux x86-64 glibc archive and published
`SHA256SUMS`, verifies the archive, and runs the native qualification through the
real stdio MCP server.

The workflow then takes the exact canonical source retained by `build_get` and
runs:

```text
weavec --frontend program.wir main.weave
weavec --backend program.wir program.ll
llvm-as program.ll -o program.bc
```

It requires the generated LLVM to define `main` and contain `ret i32 42`. On
success it uploads the canonical source, MCP trace, release metadata, WIR, LLVM,
LLVM bitcode, and JUnit report as `jacquard-packaged-weavec-qualification`.
Failure runs retain the temporary build store and protocol evidence separately.
