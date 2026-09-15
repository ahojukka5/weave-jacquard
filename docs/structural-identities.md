# Structural identities

Every Jacquard list and atom has a stable `n_*` ID. Agents should target those
IDs, not source lines or byte offsets.

## Survival

An identity remains usable when the logical node survives:

- changing an atom value keeps the same ID;
- moving a node to another parent keeps the same ID;
- wrapping a node keeps the wrapped node's ID;
- edits elsewhere in the document do not reassign surviving IDs.

## Change

A new ID is assigned when a node is created:

- `create_form` and `add_atom` allocate new IDs;
- wrapping a node creates a new wrapper ID;
- copying or importing source allocates new IDs for the imported tree.

Replay may pin IDs with an explicit `node_id` on create operations so a recorded
edit sequence can be applied again. Fresh creates without that field remain
non-deterministic in ID assignment. Canonical Weave source does not include IDs,
so source text can still match.

## Invalidation

An identity is invalid when the node is absent from the selected revision. That
includes deletion of the node or of an ancestor. `identity_inspect` reports
`identity_status = invalid` rather than inventing a replacement.

## Ambiguity

Name lookup is allowed as a convenience for declarations such as `fn` and
`entry`. If more than one declaration matches, Jacquard returns
`AMBIGUOUS_TARGET` with every matching `node_id`. It never silently picks one.

Missing names and missing IDs return `MISSING_STRUCTURAL_TARGET`.

## Observation

Use these compact reads instead of rendering a whole file:

- `entity_list` — named declarations at a branch head or exact revision;
- `entity_inspect` — signature, children, and local annotated context;
- `identity_inspect` — present versus invalid for one ID;
- `node_inspect` / `node_find` — local subtree search when the entity catalog
  is too coarse.

Revision identity is part of every successful response: `revision_id` is the
state actually read, and `branch_head_revision_id` is the selected branch at
read time.
