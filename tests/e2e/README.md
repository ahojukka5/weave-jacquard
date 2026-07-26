# Real MCP qualification

These tests launch the actual `weave-mcp` stdio process with the official MCP
Python client. They do not import and call MCP tool functions directly.

## Protocol qualification

```bash
python -m pytest -m real_mcp tests/e2e/test_real_mcp.py
```

The always-runnable test initializes a real MCP session, lists the registered
tools, constructs a complete constant-returning program through atomic tool
calls, renders canonical source, reads branch history, and writes the complete
tool trace to the pytest temporary directory.

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
