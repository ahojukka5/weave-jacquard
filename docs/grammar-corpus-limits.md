# Grammar corpus resource limits

`grammar_help` derives construction guidance from the configured `weavec`
correctness corpus. The corpus is compiler-owned input, not trusted Jacquard
configuration, so indexing is bounded before files are read, parsed, rendered,
or retained in memory.

## Authority

The index reports forms, observed arities, observed parent forms, and small
examples. These observations are guidance only. `weavec --frontend` remains the
authoritative language validator, and a truncated corpus must never be interpreted
as proving that an unobserved form or relationship is invalid.

## Corpus admission

The surface directory is enumerated once with these ceilings:

| Limit | Value |
|---|---:|
| directory entries inspected | 16,384 |
| `.weave` files selected | 4,096 |
| bytes in one source | 4 MiB |
| aggregate admitted source bytes | 64 MiB |

Files are selected in lexical filename order. Exceeding the file or aggregate-byte
limit produces a deterministic prefix and sets `corpus_truncated=true`.

Directory-entry overflow fails closed instead of indexing an arbitrary prefix from
filesystem enumeration order. The status then reports `available=false` and a
bounded `corpus_error`.

Each selected source must be a stable non-symlink regular file. The same
race-resistant reader used for retained artifact metadata rejects symlinks,
non-regular files, replacement during open, and limit overflow before decoding.
Invalid UTF-8 and parser failures are diagnostics rather than server-startup
failures.

Every admitted byte counts toward the aggregate budget even when decoding or
parsing later fails.

## Index bounds

The in-memory index has independent ceilings:

| Limit | Value |
|---|---:|
| distinct forms | 16,384 |
| observed arities per form | 256 |
| observed parents per form | 1,024 |
| retained examples per form | 12 |
| example render attempts | 4,096 |
| nodes in one rendered example | 256 |
| bytes in one rendered example | 64 KiB |
| aggregate retained example bytes | 16 MiB |
| retained parse-failure records | 256 |
| bytes in one retained error message | 1 KiB |
| `grammar_help` result limit | 1–50 |

Example subtree size is checked before rendering, so a large accepted program
cannot force repeated rendering of complete subtrees. Counters continue to record
total parse failures even after diagnostic retention reaches its ceiling.

## Truncation evidence

`grammar_help` status includes:

- discovered, considered, and successfully scanned file counts;
- admitted source bytes;
- indexed form count;
- example attempts and retained example bytes;
- total and retained parse-failure counts;
- `corpus_truncated`, `forms_truncated`, and `examples_truncated`;
- `corpus_error`;
- the complete effective limit set.

Each returned form also reports whether its arity, parent, or example evidence was
truncated. Consumers should treat these flags as incomplete observational evidence,
not as language errors.

## Compatibility rule

Changing a limit changes the amount of optional grammar guidance available but
must not change accepted Weave syntax. Limit changes require boundary tests and
real MCP qualification because they alter response evidence and may change the
public tool-contract behavior even when the input schema is unchanged.
