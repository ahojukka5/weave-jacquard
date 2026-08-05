# Artifact storage package

Artifact storage is the read-only accounting domain that measures complete
logical path usage across configured retained-artifact roots. Its implementation
lives under `weave_frontend.artifacts.storage` rather than prefix-named modules
at the package root.

## Public boundary

Cross-domain Python code imports supported symbols from:

```python
from weave_frontend.artifacts.storage import ArtifactLifecycleStorageService
```

The package publishes base logical accounting, lifecycle-aware retained versus
quarantine accounting, stable report and root identity formats, and bounded scan
limits.

## Internal responsibilities

- `accounting.py` measures complete logical bytes and entry counts without
  following links or double-counting nested roots;
- `lifecycle.py` extends base accounting with the reserved quarantine capsule
  namespace and retained-versus-quarantined totals.

## Dependency direction

Lifecycle accounting depends internally on `.accounting`. Runtime composition
constructs lifecycle accounting from configured artifact roots. Quota admission
consumes the public storage boundary but remains a separate domain because it
owns locking, policy, staged-publication measurement, and admission decisions.

Stored formats, root identities, scan limits, snapshot identities, error codes,
and MCP report behavior are unchanged. The old root-level Python import paths
are removed without forwarding modules or deprecated aliases.
