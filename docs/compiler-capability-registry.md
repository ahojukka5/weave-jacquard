# Compiler capability registry

Jacquard treats the final user-facing `weavec` executable as the authority for the
Weave language and compiler protocols. It does not infer that contract from help
text, filenames, bootstrap repositories, or the coverage of a correctness corpus.

The compiler publishes its contract with:

```sh
weavec capabilities --json
```

The output is the compiler-owned `weavec-capabilities-v1` document specified in
[`weavec` documentation](https://github.com/ahojukka5/weavec/blob/master/docs/capabilities.md).

## Startup and caching boundary

Jacquard invokes the capability command through the bounded process supervisor.
The command has explicit wall-clock and combined-output ceilings. The result must
be valid UTF-8 JSON and must identify:

- the final public `weavec` variant;
- `weave-surface-v1` and `weave-surface-grammar-v1`;
- WIR core version 2;
- the capability, build-manifest, diagnostics, trace, and WIR protocols;
- the public build and frontend commands;
- at least one installed target including the declared default target;
- a non-empty machine-readable surface-form registry.

The validated document is cached by the exact compiler binary SHA-256. Replacing
the bytes at the configured compiler path therefore invalidates the cached
registry and forces a new bounded handshake.

Unknown additive object fields remain compatible. Unknown top-level formats,
incompatible mandatory versions, missing commands or protocols, unsupported
public variants, malformed target declarations, and inconsistent surface forms
fail closed with stable `WEAVEC_*` errors.

## Grammar ownership

`grammar_help` uses `weavec-capabilities-v1` as the authoritative source for form
heads, status, child-count bounds, type-information mode, feature dependencies,
roles, and canonical replacements.

The optional `WEAVEC_SOURCE_ROOT` correctness corpus remains useful for concrete
examples, observed parent relationships, and exploratory search. These facts are
reported as observational evidence and never promoted into a second normative
grammar. A form can therefore be authoritatively known even when the local corpus
is absent or contains no example of it.

## Validation and build admission

Production frontend validation requires the installed compiler to advertise the
`frontend` command and `weave-wir-core-v2` before source materialization.
Revisioned build-target validation also checks the requested target against the
installed target inventory.

Committed builds require the public `build` command and the build-manifest,
diagnostics, trace, and WIR protocols before invoking the compiler. The returned
build and validation evidence includes the path-free registry identity:

- exact registry SHA-256 and byte count;
- exact compiler binary SHA-256 and byte count;
- compiler version;
- surface and grammar identifiers;
- WIR core version;
- default installed target.

The compiler binary hash already participates in Jacquard build identity. The
explicit registry identity makes the compatible contract inspectable without
publishing local compiler paths.

## Runtime identity

`runtime_identity` reports the same validated registry identity under the compiler
component. A compiler may have a working `--version` command while still exposing
an incompatible public contract; those states are reported separately. Registry
failures are redacted and become part of the content-derived runtime identity.

## Dependency boundary

Jacquard invokes only the final `weavec` executable. It does not import compiler
implementation modules or depend on `weavec0`, `weavec1`, or
`weavec-bootstrap`. The compiler remains independently installable and never
depends on Jacquard.
