# Builds package

Immutable build discovery, retained diagnostic inspection, race-safe target mutation,
and metadata-aware target policy are owned incrementally by
`weave_frontend.builds`.

## Public boundary

Cross-domain production code imports supported services from:

```python
from weave_frontend.builds import (
    BuildDiscoveryService,
    BuildInspectionService,
    ConcurrentBuildTargetRegistry,
    MetadataBuildTargetRegistry,
)
```

Production callers do not import `builds.discovery`, `builds.catalog`,
`builds.inspection`, `builds.concurrency`, or `builds.metadata` directly.

## Responsibilities

- `discovery.py` validates stored build manifests, immutable revision provenance,
  build-key evidence, filters, cursors, and deterministic page contracts;
- `catalog.py` adds the production filesystem enumeration bound and publishes the
  final `BuildDiscoveryService` used by MCP composition;
- `inspection.py` reads only verified hashed mapped-diagnostic artifacts and
  exposes bounded diagnostic pages;
- `concurrency.py` extends the current target registry with bounded document sets
  and compare-and-set branch publication for race-safe target writes;
- `metadata.py` rejects reserved project metadata as compiler source and preserves
  safe build-target deletion when behavioral tests still reference a target.

The public MCP tools, stored formats, validation codes, pagination behavior, hash
checks, build-root limits, target serialization, concurrency semantics, and
reserved-metadata rules are unchanged. The former root-level `build_discovery.py`,
`verified_build_discovery.py`, `build_inspection.py`,
`concurrent_build_targets.py`, and `metadata_build_targets.py` implementation
modules are removed without forwarding aliases.

The base target representation in `build_targets.py`, target-reference integrity,
target validation, compiler publication, and the `weave-build` command remain
separate responsibilities for the next focused build-domain slices under refactor
epic #197. The temporary internal dependency from `builds.concurrency` to the base
registry is removed when that base registry moves into this package; cross-domain
callers already use the public boundary.
