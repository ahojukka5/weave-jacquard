# Builds package

Immutable build discovery, retained diagnostic inspection, and build-target policy
are owned incrementally by `weave_frontend.builds`.

## Public boundary

Cross-domain production code imports supported services from:

```python
from weave_frontend.builds import (
    BuildDiscoveryService,
    BuildInspectionService,
    ConcurrentBuildTargetRegistry,
    MetadataBuildTargetRegistry,
    validate_build_target_references,
)
```

Production callers do not import implementation modules below `builds` directly.

## Responsibilities

- `discovery.py` validates stored build manifests, immutable revision provenance,
  build-key evidence, filters, cursors, and deterministic page contracts;
- `catalog.py` adds the production filesystem enumeration bound and publishes the
  final `BuildDiscoveryService` used by MCP composition;
- `inspection.py` reads only verified hashed mapped-diagnostic artifacts and
  exposes bounded diagnostic pages;
- `concurrency.py` extends the current target registry with bounded document sets
  and compare-and-set branch publication for race-safe target writes;
- `metadata.py` adds project-metadata exclusion and test-target reference safety;
- `references.py` owns exact-state validation for build-target source references.

The public MCP tools, stored formats, validation codes, pagination behavior, hash
checks, build-root limits, target serialization, metadata semantics, and
concurrency behavior are unchanged. The former root-level `build_discovery.py`,
`verified_build_discovery.py`, `build_inspection.py`,
`concurrent_build_targets.py`, `metadata_build_targets.py`, and
`build_target_validation.py` modules are removed without forwarding aliases.

The base target representation in `build_targets.py`, compiler-facing target
validation, compiler publication, and the `weave-build` command remain separate
responsibilities for the next focused build-domain slices under refactor epic
#197. Temporary package-internal dependencies on the root base registry disappear
when that final base target layer moves into this package; cross-domain callers
already use the public boundary.
