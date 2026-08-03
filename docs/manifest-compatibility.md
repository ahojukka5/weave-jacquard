# Manifest and runtime compatibility review

Jacquard emits deterministic compatibility reports for caller-visible manifests
and for internal runtime evidence. The reports use exact JSON pointers and
bounded old/new fragments so release reviews can identify the changed contract
without relying on content hashes alone.

## Compare retained files

Compare two tool, application, service-graph, or runtime-identity documents:

```sh
weave-manifest-diff old.json new.json
```

The command selects the comparator from the document `format`. Unknown formats
and cross-family comparisons fail closed.

Supported evidence families are:

- `weave-jacquard-tool-manifest-v1` and `-v2`;
- `weave-jacquard-application-v2`;
- `weave-jacquard-runtime-service-graph-v1`;
- `weave-jacquard-runtime-identity-v1`.

Service-graph reports compare static service names, factory origins, and
dependencies. Materialized-service state is validated but excluded because it
describes one process moment rather than the declared graph.

Runtime-identity reports compare application, interpreter, MCP, database,
compiler, sandbox, and redacted configuration components. Component changes are
classified as `behavior-review-required`; identical evidence produces an empty
`identity-only` report.

## Compare an installed application

Compare a retained contract with the public contract exported by the currently
installed Jacquard package:

```sh
weave-manifest-diff old-tool-manifest.json --installed tool
weave-manifest-diff old-application-manifest.json --installed application
```

The installed comparison reads only the immutable public manifests. It does not
open a workspace database or instantiate runtime services.

## Compare retained release evidence

Use the release reviewer when both qualifications contain canonical manifest
evidence:

```sh
weave-release-compatibility previous-evidence current-evidence
```

Intentional changes require a content-addressed reviewed policy as described in
[`release-compatibility.md`](release-compatibility.md). Caller-visible release
policy remains separate from service-graph and runtime-component evidence.
