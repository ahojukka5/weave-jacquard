# Verified stored-build discovery

## Purpose

`build_get` is the authoritative detailed read for one immutable build, but it
requires an exact build ID. `build_list_page` lets a restarted or disconnected
agent recover build IDs without trusting directory names or opening arbitrary
server-local files.

Discovery is a bounded verified scan, not a database index and not a chronology.
Build IDs are content-derived hashes, and the current stored manifest format has
no immutable creation timestamp. The catalog therefore uses deterministic lexical
build-ID order.

## Request

```text
build_list_page(
  project,
  branch = optional,
  revision_id = optional,
  status = optional "succeeded" or "failed",
  document = optional source included by the build,
  target = optional requested compiler target,
  start_after_build_id = optional cursor,
  catalog_id = optional prior catalog identity,
  limit = 50)
```

`limit` is the maximum number of catalog members scanned in one call, not a
promise that the same number of project-matching builds will be returned. It must
be between 1 and 200.

The project must exist before filesystem discovery starts.

## Candidate catalog

A catalog member must be a direct, non-symlink directory below
`WEAVE_BUILD_ROOT` whose name is a 32-character lowercase hexadecimal build ID
and which contains a non-symlink regular `manifest.json`.

Temporary directories, lock files, quarantine names, symlinks, malformed names,
and directories without a regular manifest are not catalog members.

The `weave-build-catalog-v1` `catalog_id` is SHA-256 over the sorted catalog
membership. Its scope is explicitly `build-root-membership`.

The identity binds membership and lexical order. It does not claim that every
member is valid; validity is established separately when that member is scanned.
It also does not hide later corruption: each page re-verifies artifact bytes at
read time.

## Pagination

The first page omits both cursor fields. When `has_more=true`, pass:

```text
start_after_build_id = previous next_after_build_id
catalog_id = previous catalog_id
```

`start_after_build_id` is an exclusive lexical cursor. Supplying the previous
catalog identity makes a multi-page read reject build-directory additions or
removals with `STALE_BUILD_CATALOG`.

A caller may omit `catalog_id` to intentionally read the current live catalog,
but then pages do not represent one membership snapshot.

Every response reports:

- `catalog_build_count`;
- `scanned_count`;
- `returned_count`;
- `filtered_count`;
- `rejected_count`;
- `has_more` and `next_after_build_id`;
- compact `builds` and `rejected_builds` arrays.

A page can legitimately return no project builds while still advancing the
cursor because scanned members may belong to another project, fail filters, or
be rejected.

## Verification and isolation

Every scanned catalog member is passed through the same `build_get` verification
path used for direct inspection. Before a usable summary is returned, Jacquard
checks:

- manifest format and build-ID/directory agreement;
- artifact path containment;
- exact artifact-reference/hash-key agreement;
- regular-file status;
- lowercase SHA-256 values and current artifact checksums;
- core discovery metadata such as project, branch, revision, ordered documents,
  target, compiler hash, and build-key format.

Only verified manifests matching `project` and all requested filters appear in
`builds`. Valid builds from other projects are counted in `filtered_count` but
not returned.

Malformed or corrupt members appear only as:

```json
{"build_id": "...", "code": "CORRUPT_BUILD_ARTIFACT"}
```

They never produce a usable build summary. A member that disappears during a
scan is reported as `BUILD_NOT_FOUND_DURING_SCAN`.

## Compact summary

A returned build summary contains enough identity to choose a subsequent read:

- build ID, status, project, and branch;
- revision ID and revision hash;
- primary and ordered source documents;
- requested and compiler-reported targets;
- compiler SHA-256 and build-key format;
- return code and protocol-validity flags;
- executable and diagnostics availability.

It deliberately omits `build_directory`, `artifact_paths`, raw command output,
and diagnostic entries. Use:

```text
build_list_page
→ choose build_id
→ build_get
→ build_diagnostics_page when needed
```

`build_get` remains the verified detailed manifest and absolute-path boundary.

## Filters

Filters are applied only after verification:

- `branch` matches the branch recorded at build time;
- `revision_id` matches the exact immutable revision;
- `status` matches `succeeded` or `failed`;
- `document` matches any ordered source document, not only the primary source;
- `target` matches the requested target stored in the frontend manifest.

Because pagination is over the global build-root membership, filters can produce
sparse or empty pages. Continue with the returned cursor until `has_more=false`.

## Failure codes

- `INVALID_BUILD_LIST_LIMIT`;
- `INVALID_BUILD_LIST_FILTER`;
- `INVALID_BUILD_LIST_CURSOR`;
- `INVALID_BUILD_CATALOG_ID`;
- `STALE_BUILD_CATALOG`;
- `BUILD_CATALOG_UNAVAILABLE`.

Per-member verification failures are returned in `rejected_builds` instead of
failing the complete page. Request-level errors fail the page before any build is
returned.

## Qualification

The real stdio MCP qualification builds through packaged `weavec v0.3.0`:

1. two successful revisions of one project;
2. one compiler-rejected revision of that project;
3. one successful build belonging to another project;
4. one malformed catalog member.

It then proves:

- five catalog members are scanned through one-member pages;
- three verified project builds are recovered;
- one foreign build is filtered;
- one malformed manifest is rejected;
- status/revision/document/target filters recover the failed build;
- a discovered successful ID remains readable through `build_get`;
- adding another catalog member invalidates the prior `catalog_id`.

The packaged workflow retains `build-discovery-trace.json` with the complete
request and response evidence.
