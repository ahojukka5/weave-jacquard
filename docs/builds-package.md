# Build evidence package

Immutable build discovery and retained diagnostic inspection are owned by
`weave_frontend.builds`.

## Public boundary

Cross-domain production code imports the supported build-evidence services and
format constants from:

```python
from weave_frontend.builds import BuildDiscoveryService, BuildInspectionService
```

Production callers do not import `builds.discovery`, `builds.catalog`, or
`builds.inspection` directly.

## Responsibilities

- `discovery.py` validates stored build manifests, immutable revision provenance,
  build-key evidence, filters, cursors, and deterministic page contracts;
- `catalog.py` adds the production filesystem enumeration bound and publishes the
  final `BuildDiscoveryService` used by MCP composition;
- `inspection.py` reads only verified hashed mapped-diagnostic artifacts and
  exposes bounded diagnostic pages.

The public MCP tools, stored formats, validation codes, pagination behavior, hash
checks, and build-root limits are unchanged. The former root-level
`build_discovery.py`, `verified_build_discovery.py`, and `build_inspection.py`
implementation modules are removed without forwarding aliases.

Build-target mutation, target validation, compiler publication, and the
`weave-build` command remain separate root-level responsibilities for the next
build-domain slice under refactor epic #197. This package therefore establishes a
reviewed boundary without prematurely moving unrelated build-target behavior.
