# Revisioned target validation

`build_target_validate` validates the same immutable target definition consumed by
`build_target_build`.

```text
branch or explicit revision
    ↓ pin once
build target metadata + ordered source documents
    ↓ canonical rendering
weavec --frontend output.wir source0.weave source1.weave ...
```

The operation resolves the target and every selected source document from one
revision. It never reads a target from one revision and source content from a
later branch head.

The primary document is passed first. Additional documents preserve the order
stored in the target. Validation uses the same canonical renderer as native
builds, so the compiler sees the same source representation in both operations.

Example MCP workflow:

```text
build_target_set(
  project="demo",
  name="application",
  document="main.weave",
  additional_documents=["library.weave", "platform.weave"]
)
→ build_target_validate(project="demo", name="application")
→ build_target_build(project="demo", name="application")
```

The returned result records the pinned revision, ordered documents, target
configuration, root node IDs, frontend status, diagnostics streams, and WIR when
validation succeeds.

`program_validate` remains the lightweight single-document operation. Named
target validation is the authoritative operation for multi-document programs.
