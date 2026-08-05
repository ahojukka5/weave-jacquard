# Artifact quota package

Artifact quota is the publication-admission domain that serializes aggregate
logical-byte policy checks across all retained artifact families. Its
implementation lives under `weave_frontend.artifacts.quota` rather than
prefix-named modules at the package root.

## Public boundary

Cross-domain Python code imports supported symbols from:

```python
from weave_frontend.artifacts.quota import ArtifactQuotaService
```

The package publishes quota policy parsing and formats, the aggregate admission
service, owner-attached admission context managers, and the reusable publication
lock mixin.

## Internal responsibilities

- `service.py` owns policy, reporting, interprocess locking, staged measurement,
  quota decisions, and admission evidence;
- `admission.py` adapts an optional quota service attached to another runtime
  service;
- `publication.py` composes aggregate quota admission ahead of an artifact's
  normal per-item publication lock.

## Dependency direction

Quota depends on the public `artifacts.storage` accounting boundary. Admission
depends internally on `.service`, and publication depends internally on
`.admission`. Runtime composition and quota-aware compiler, test, attestation,
and backup services consume only the package public boundary.

Environment variables, report and policy formats, lock identities, limits,
error codes, admission evidence, and publication behavior are unchanged. The old
root-level Python import paths are removed without forwarding modules or
deprecated aliases.
