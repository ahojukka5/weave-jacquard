# Artifact retention package

Artifact retention is the read-only policy and planning domain for retained
artifacts. Its implementation lives under `weave_frontend.artifacts.retention`
rather than a family of prefix-named modules at the package root.

## Public boundary

Cross-domain Python code imports supported symbols from:

```python
from weave_frontend.artifacts.retention import ArtifactRetentionPlanner
```

The package `__init__.py` is the reviewed public boundary. It publishes the
planner, policy normalization and canonical identity functions, bounded policy
input, accounting and catalog services, stored format names, and limits required
by downstream artifact lifecycle domains.

Operator command parsing and `main` remain explicit in
`weave_frontend.artifacts.retention.cli`; they are not part of the cross-domain
Python API.

## Internal responsibilities

- `planner.py` creates deterministic mutation-free retention plans;
- `policy.py` validates policies and owns canonical identities;
- `policy_io.py` reads bounded UTF-8 JSON policies for operator adapters;
- `accounting.py` performs stable no-follow filesystem accounting;
- `catalog.py` binds reconciliation evidence to live retained entries;
- `cli.py` adapts operator input and output to the public planning API.

## Dependency direction

Retention may depend on reconciliation evidence, inventory contracts, runtime
composition used by its CLI, and shared frontend errors. Quarantine depends on
the public retention boundary because it consumes exact retention plans and the
bounded policy input; it must not import retention implementation submodules.

The command name, policy and plan formats, error codes, limits, and planning
behavior are unchanged. No old import-path forwarding modules are retained.
