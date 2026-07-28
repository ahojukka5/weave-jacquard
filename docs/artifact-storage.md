# Artifact storage accounting

The `artifact_storage_report` MCP tool measures the complete logical footprint of
all retained artifact families used by one live Jacquard server and reports the
active aggregate publication quota.

## Included families

The production report composes roots from the active services:

- committed revision builds;
- virtual merge-candidate builds;
- committed test runs;
- committed test batches;
- virtual-candidate test qualifications;
- tested-merge attestations.

The service reads the same resolved roots used by publication and inspection. It
does not infer paths independently from environment variables.

## Logical accounting

The public report counts:

- logical bytes in regular files;
- regular-file count;
- directory count;
- symlink count;
- other filesystem-object count;
- entries inspected;
- largest regular file in each family.

Logical bytes count each retained file path by its reported size. They are not a
filesystem allocation estimate: sparse files, compression, reflinks, and hard
links may use a different number of physical blocks.

Symlinks are counted but never followed. FIFOs, devices, sockets, and other
non-regular entries are counted as special entries and contribute no logical file
bytes.

The public operational report includes dot-prefixed temporary, lock, and
quarantine entries. Quota admission separately excludes those internal entries and
adds only the exact staged publication under review. This distinction prevents
concurrent staging from consuming retained quota before publication while keeping
temporary filesystem use visible to operators.

## Nested roots

Default storage composition contains nested families:

```text
committed build root
└── virtual-candidate build root

committed test-run root
└── committed test-batch root
```

Jacquard assigns every nested subtree to its most specific configured family. A
parent scan records the nested family name and does not descend into that subtree.
The child family then owns its root directory and contents. Aggregate logical bytes
and file counts therefore do not double count nested stores.

Two families resolving to exactly the same directory are rejected with
`ARTIFACT_STORAGE_ROOT_CONFLICT`. Exact overlap is ambiguous and cannot be assigned
without hiding one family's usage.

## Scan limits

One report is limited to:

| Boundary | Limit |
|---|---:|
| artifact roots | 16 |
| entries across all roots | 1,000,000 |
| directory depth below a root | 64 |

The entry budget is global and counts every encountered path, including excluded
nested-root directory entries, junk files, temporary directories, malformed
artifact names, and symlinks.

Overflow fails the complete report with:

- `ARTIFACT_STORAGE_SCAN_LIMIT_EXCEEDED`;
- `ARTIFACT_STORAGE_DEPTH_EXCEEDED`;
- `ARTIFACT_STORAGE_ROOT_UNAVAILABLE`;
- `ARTIFACT_STORAGE_ROOT_INVALID`;
- `ARTIFACT_STORAGE_SCAN_FAILED`.

Jacquard never labels a truncated scan complete and never computes a storage
snapshot ID from partial accounting.

## Redaction and identity

Raw root paths are absent from the response. Every family has a domain-separated
`root_id` derived from its family name and resolved path. The IDs let reports
compare root configuration without exposing paths directly. Path-like values may
have low entropy, so these hashes are matching evidence rather than secret-storage
primitives.

`storage_snapshot_id` is SHA-256 over canonical JSON containing all counts, root
IDs, nesting assignments, limits, and accounting semantics. The report contains no
timestamp or random value. Repeated scans of unchanged stores and configuration
produce the same ID.

The quota section adds:

- whether aggregate admission is enabled;
- the configured logical-byte ceiling;
- current and available logical bytes;
- whether existing retained content already exceeds the ceiling;
- a path-redacted interprocess lock ID;
- content-derived quota policy and combined snapshot IDs.

The filesystem is not frozen while a public report runs. The result is a bounded
read-only operational snapshot. Publication admission performs a new scan while
holding the quota lock and is never authorized by an earlier report ID.

## Policy boundary

When `WEAVE_ARTIFACT_MAX_BYTES` is configured, all six production MCP publishers
use one shared interprocess admission lock and reject projected overflow before the
normal atomic publication step. See [artifact quota](artifact-quota.md).

The capability still does not:

- delete or quarantine retained artifacts as policy action;
- implement age- or reachability-based retention;
- measure physical filesystem blocks;
- include the SQLite database or external qualification evidence directories;
- bound temporary compiler and test staging bytes as a separate physical-storage
  policy.

Retention and garbage collection require verified reachability and explicit
operator authorization. Database and temporary-space ceilings require independent
policies rather than being inferred from retained logical-byte quota.
