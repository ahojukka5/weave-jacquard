# Runtime identity

The `runtime_identity` MCP tool reports the exact Jacquard application and active
execution components used by one server process.

## Purpose

A stored build or audit is useful only when its producing software and runtime
contract can be identified. The report binds:

- installed Jacquard distribution version;
- public application ID;
- public MCP tool-manifest ID and tool count;
- capability count;
- Python implementation, version, and executable hash;
- MCP SDK version;
- SQLite schema version, busy timeout, journal mode, and foreign-key policy;
- final `weavec` binary hash and bounded `--version` identity;
- strict sandbox capability report and Bubblewrap and `prlimit` binary hashes;
- the public configuration-variable names and which ones are set;
- one content-derived runtime ID covering the complete report.

The application and tool-manifest IDs come from the completed public composition,
not from a parallel hand-maintained inventory.

## Redaction

Configuration values are never returned. The report exposes only:

- the configuration-variable names already bound into the application manifest;
- the subset whose values are non-empty;
- component hashes and public capability evidence.

Compiler resolution failures are normalized by error code. Configured executable
paths and raw filesystem exception text are not returned.

## Compiler probe bounds

Compiler identity uses the same final user-facing `weavec` selected by the active
compiler bridge. The binary is opened as a stable regular file and hashed through
the file descriptor. `weavec --version` is limited to:

```text
5 seconds
4,096 captured bytes
```

Timeout, output overflow, nonzero exit, empty output, missing compiler, and
non-executable compiler are retained as structured availability evidence rather
than failing the whole runtime report.

## Sandbox identity

The sandbox section contains the canonical public policy and policy hash, effective
resource-limit support, availability, and bounded version evidence. Bubblewrap and
`prlimit` are hashed without exposing their configured paths.

A missing or unavailable sandbox remains visible in the report. Runtime identity
does not weaken test-run admission: behavioral execution still fails closed unless
the canonical sandbox capability probe succeeds.

## Content-derived runtime ID

The report is canonicalized as UTF-8 JSON with sorted keys, no insignificant
whitespace, and non-finite numbers forbidden. `runtime_id` is the SHA-256 hash of
every field except `runtime_id` itself.

The ID changes when any bound component changes, including:

- application or tool contract;
- Jacquard, MCP, or Python version;
- Python, compiler, Bubblewrap, or `prlimit` binary content;
- database runtime policy;
- compiler version evidence;
- sandbox policy or availability;
- which public configuration variables are set.

The report intentionally contains no wall-clock timestamp, random identifier, or
mutable counter, so repeated calls against an unchanged process return the same
identity.

## Relationship to qualification

`runtime_identity` describes one live server. `scripts/qualify.sh` remains the
release-strength evidence producer and additionally records tested Git commit,
full package inventory, platform, test selection, traces, coverage, compiler and
sandbox identities, completion status, and checksums.

A runtime report is therefore useful for diagnostics, audit correlation, and agent
planning, but it does not claim that the running process has passed full
qualification.
