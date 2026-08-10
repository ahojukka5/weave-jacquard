# Runtime identity

The `runtime_identity` MCP tool reports the exact Jacquard application and active
execution components used by one server process.

## Implementation boundary

Runtime identity generation and runtime-evidence compatibility are owned by the
public `weave_frontend.runtime` domain. Cross-domain callers import supported
identity formats, comparison functions, errors, and `RuntimeIdentityService` from
that boundary rather than implementation submodules.

`mcp_runtime_identity.py` remains a thin MCP composition adapter: it binds the
runtime-owned identity service to the active workspace, compiler, sandbox, and
service graph and registers the public tool. It does not own the identity format
or compatibility policy. No forwarding aliases for the former root-level runtime
identity modules are retained.

## Purpose

A stored build or audit is useful only when its producing software and runtime
contract can be identified. The report binds:

- installed Jacquard distribution version;
- public application ID;
- public MCP tool-manifest ID and tool count;
- capability count;
- the typed runtime service graph and its content-derived graph ID;
- Python implementation, version, and executable hash;
- MCP SDK version;
- SQLite schema version, busy timeout, journal mode, foreign-key policy, and an
  opaque database-location ID;
- final `weavec` binary hash and bounded `--version` identity;
- strict sandbox capability report and Bubblewrap and `prlimit` binary hashes;
- the public configuration-variable names, which ones are set, and opaque IDs for
  their values;
- one content-derived runtime ID covering the complete report.

The application and tool-manifest IDs come from the completed public composition,
not from a parallel hand-maintained inventory.

## Typed service graph

The `service_graph` section uses
`weave-jacquard-runtime-service-graph-v1`. It records every service currently owned
by the typed runtime registry as a lexical list containing:

- stable service name;
- Python factory origin;
- explicit dependency names.

Its `service_graph_id` covers the graph format, service count, and complete service
list. Lazy initialization state is deliberately excluded. Calling a previously
unused service therefore does not redefine the runtime identity.

The graph is incremental while issue #106 is open. It currently includes the
workspace, compiler bridge, foundational build and merge services, and runtime
identity itself. Legacy capability caches are not falsely represented as
runtime-owned services before they migrate.

## Redaction and opaque configuration IDs

Configuration values are never returned. The report exposes:

- the configuration-variable names already bound into the application manifest;
- the subset whose values are non-empty;
- a domain-separated SHA-256 value ID for each configured value;
- a domain-separated ID for the resolved database location;
- component hashes and public capability evidence.

The value ID input is:

```text
weave-jacquard-configuration-value-v1 NUL variable-name NUL value
```

This lets two runtime reports prove whether their configuration values match
without revealing the values themselves. The IDs are identity evidence rather
than password hashes: path-like configuration values may have low entropy and
must not be treated as secrets solely because only their hashes are returned.

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
- typed runtime service composition;
- Jacquard, MCP, or Python version;
- Python, compiler, Bubblewrap, or `prlimit` binary content;
- database location or runtime policy;
- compiler version evidence;
- sandbox policy or availability;
- which public configuration variables are set;
- any configured public value, through its opaque value ID.

The report intentionally contains no wall-clock timestamp, random identifier,
mutable counter, or lazy-initialization state, so repeated calls against an
unchanged process return the same identity.

## Relationship to qualification

`runtime_identity` describes one live server. `scripts/qualify.sh` remains the
release-strength evidence producer and additionally records tested Git commit,
full package inventory, platform, test selection, traces, coverage, compiler and
sandbox identities, completion status, and checksums.

A runtime report is therefore useful for diagnostics, audit correlation, and agent
planning, but it does not claim that the running process has passed full
qualification.
