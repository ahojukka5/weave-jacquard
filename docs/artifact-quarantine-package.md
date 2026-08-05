# Artifact quarantine package

Artifact quarantine is one retained-artifact lifecycle domain. Its implementation
lives under `weave_frontend.artifacts.quarantine`; it is no longer represented by
a family of `artifact_quarantine_*` modules at the package root.

## Public boundary

Cross-domain Python code imports services and supported constants from:

```python
from weave_frontend.artifacts.quarantine import ArtifactQuarantineService
```

The package `__init__.py` is the reviewed public boundary. Modules inside the
package are implementation responsibilities, not independent application domains.
CLI entry points may target the explicit `cli`, `lifecycle_cli`, and
`restoration_cli` adapters.

## Internal responsibilities

- `service.py` publishes one guarded quarantine capsule;
- `contract.py` owns canonical quarantine identities and validation;
- `state.py`, `io.py`, and `verification.py` own state capture, durable I/O, and
  exact verification;
- `deletion.py` and `deletion_batch.py` own permanent deletion;
- `restoration.py` and `restoration_contract.py` own verified restoration;
- the three CLI modules translate command-line input into the domain API.

## Dependency direction

The quarantine package may depend on the existing artifact retention,
reconciliation, storage, database, and error boundaries. Those domains must not
import quarantine implementation submodules. Callers cross the boundary only
through `weave_frontend.artifacts.quarantine`.

Stored formats, command names, and lifecycle behavior are unchanged by this
package refactor. No old import-path forwarding modules are retained.
