# Build catalog enumeration limits

`build_list_page` recovers committed build IDs from the retained build root. The
page size bounds manifest verification, but it does not by itself bound the work
needed to discover and sort catalog membership. Jacquard therefore applies a
separate root-entry ceiling before catalog identity is computed.

## Entry ceiling

Production discovery inspects at most:

```text
65,536 direct entries below WEAVE_BUILD_ROOT
```

The limit counts every direct entry, including malformed names, lock files,
quarantine remnants, temporary directories, and other junk. Counting only valid
build directories would allow unrelated files to force unbounded enumeration.

Exactly 65,536 entries are accepted. Encountering a 65,537th entry fails the
request with:

```text
BUILD_CATALOG_LIMIT_EXCEEDED
```

The service does not return a truncated catalog. A truncated lexical membership
set could produce a plausible but incomplete `catalog_id`, hide valid builds, and
make pagination semantics depend on filesystem enumeration order.

## Candidate membership

After bounded enumeration, candidate members retain the existing requirements:

- direct child directory;
- 32-character lowercase hexadecimal name;
- directory itself is not a symlink;
- contains a non-symlink regular `manifest.json`.

Candidate IDs are sorted lexically only after the root-entry ceiling has been
satisfied. Each page then verifies selected candidates through the normal
`build_get` path before returning a summary.

## Catalog identity

The `weave-build-catalog-v1` identity remains SHA-256 over complete sorted candidate
membership. It binds membership, not manifest validity or artifact bytes. A prior
`catalog_id` still rejects additions and removals with `STALE_BUILD_CATALOG`, and
every selected member is reverified at read time.

## Operator response

A catalog-limit error indicates that the retained root requires operator action.
The correct response is to inspect retention state, stale temporary or quarantine
content, and storage policy. Increasing the ceiling is a compatibility and resource
policy change requiring boundary tests and qualification; it is not an automatic
recovery mechanism.

Aggregate retained bytes, per-family quotas, retention, and guarded garbage
collection remain separate operator capabilities.
