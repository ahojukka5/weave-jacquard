# Artifact reconciliation package

Artifact reconciliation is the read-only domain that inventories retained
artifact roots and connects verified artifacts to immutable database
reachability. Its implementation lives under
`weave_frontend.artifacts.reconciliation` rather than misleading root-level
modules.

## Public boundary

Cross-domain Python code imports supported symbols from:

```python
from weave_frontend.artifacts.reconciliation import ArtifactReconciliationService
```

The package `__init__.py` publishes retained-family definitions, bounded
inventory services and contracts, reconciliation services, stored format names,
and limits. Operator parsing and `main` remain explicit in
`weave_frontend.artifacts.reconciliation.cli` and are not part of the
cross-domain Python API.

## Internal responsibilities

- `inventory.py` enumerates and classifies complete retained-family membership;
- `service.py` connects one stable database snapshot to verified inventory and
  produces deterministic reachability evidence;
- `cli.py` adapts operator invocation to the production runtime service.

## Dependency direction

Reconciliation depends on database integrity and shared frontend errors. Runtime
composition constructs configured family verifiers and the database binding.
Retention and quarantine consume only the public reconciliation boundary; they
must not import reconciliation implementation submodules.

The command name, inventory and reconciliation formats, identities, limits,
error codes, and report behavior are unchanged. No old import-path forwarding
modules are retained.
