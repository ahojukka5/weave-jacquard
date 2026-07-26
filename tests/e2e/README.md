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
  python -m pytest -m real_e2e tests/e2e
```

The basic native test validates through `weavec --frontend`, builds through
`weavec build`, verifies stored artifacts through `build_get`, executes the
returned binary, and requires exit status 42.

The complex program matrix additionally constructs every form and atom through
MCP for three progressively harder programs:

| Case | Language/runtime coverage | Nodes | MCP calls | Revisions | Exit |
|---|---|---:|---:|---:|---:|
| `while-accumulator` | locals, loop-carried values, comparison, mutation | 41 | 48 | 43 | 42 |
| `multi-function-chain` | parameters, three helper calls, arithmetic | 59 | 66 | 61 | 35 |
| `memory-flow` | allocation, pointer arithmetic, stores, loads, two loops, free | 136 | 143 | 138 | 100 |

For each case the test:

1. renders canonical source;
2. validates and requires non-empty WIR;
3. builds and verifies compiler manifest and diagnostics protocols;
4. executes the native program;
5. regenerates WIR and LLVM from the exact retained source;
6. assembles the LLVM with `llvm-as`;
7. checks case-specific LLVM instructions and calls;
8. records artifact sizes, build ID, node count, MCP call count, and complete
   reachable revision count.

The compiler-backed tests skip when `WEAVEC_BIN` is unset or not executable.
Native execution is currently POSIX-only.

## Packaged compiler qualification in CI

`.github/workflows/native-e2e.yml` resolves the immutable `weavec v0.3.0`
release metadata, selects the unique Linux x86-64 glibc archive and published
`SHA256SUMS`, verifies the archive, and runs the complete native matrix through
the real stdio MCP server.

Success uploads release metadata, JUnit output, the aggregate matrix summary,
and the complete pytest temporary tree. The retained tree includes canonical
sources, MCP traces, Jacquard build stores, compiler manifests and diagnostics,
WIR, LLVM, bitcode, and native executables. Failure runs retain the same evidence
separately for diagnosis.
