# Builds package

Immutable build discovery, retained diagnostic inspection, build-target policy, and
compiler-facing target validation are owned by `weave_frontend.builds`.

## Public boundary

Cross-domain production code imports supported services from:

```python
from weave_frontend.builds import (
    BUILD_TARGET_PREFIX,
    BuildDiscoveryService,
    BuildInspectionService,
    BuildTargetRegistry,
    BuildTargetValidator,
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
- `targets.py` owns the base revisioned build-target representation, serialization,
  source ordering, named target lookup, and compiler evidence-profile selection;
- `concurrency.py` extends the base registry with bounded document sets and
  compare-and-set branch publication for race-safe target writes;
- `metadata.py` adds project-metadata exclusion and test-target reference safety;
- `references.py` owns exact-state validation for build-target source references;
- `validation.py` validates the exact target revision and ordered source set through
  the configured compiler frontend while retaining compiler capability identity.

The public MCP tools, stored formats, validation codes, pagination behavior, hash
checks, build-root limits, target serialization, metadata semantics, concurrency
behavior, CLI commands, and compiler validation evidence are unchanged. The former
root-level `build_discovery.py`, `verified_build_discovery.py`,
`build_inspection.py`, `build_targets.py`, `concurrent_build_targets.py`,
`metadata_build_targets.py`, `build_target_validation.py`, and
`target_validation.py` modules are removed without forwarding aliases.

Compiler publication and the `weave-build` entry point remain cross-domain
adapters; all target-domain dependencies enter through the public builds boundary.
