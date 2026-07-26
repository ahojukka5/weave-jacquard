"""Runtime guidance exposed to coding agents through the MCP server."""

from __future__ import annotations

from typing import Any, Protocol

INSTRUCTIONS = """
Build Weave programs with stable-ID structural edits. Use single-node tools while
exploring or repairing code. Once a coherent local structure is known, use
node_apply_batch with a bounded flat operation list and temporary @aliases so the
whole edit commits as one immutable revision or rolls back completely. Call
grammar_help before using an unfamiliar Weave form. Use expected_revision_id for
optimistic concurrency. Use program_validate for a coherent single document. For
a multi-document program, define a named target and use build_target_validate so
the target metadata and ordered sources are validated from one pinned revision.
Before combining independent branches, call branch_merge_preflight. Review its
bounded directional impact, uncovered documents, and complete affected-target
compiler evidence. When ready_for_publication is true, call the returned
publication_tool with publication_arguments; publication repeats every gate and
atomically rechecks both branch heads. Use branch_merge_preview,
branch_merge_impact, branch_merge_validate, and branch_merge_validate_affected
only when investigating an individual layer. Build through program_build or
build_target_build and inspect the immutable result with build_get. When a build
fails, read mapped errors through build_diagnostics_page instead of assuming
access to server-local artifact paths. Pass the failed build revision_id to
node_inspect when the branch may have advanced, then use revision_diff_page to
compare that failing state with the current branch head before repairing. Use
branch_history_page for complete bounded history reads,
revision_operations_page for exact grouped-edit audit rows, and
branch_activity_summary to measure revision and operation grouping.
""".strip()


_TOPICS: dict[str, dict[str, Any]] = {
    "workflow": {
        "steps": [
            "project_initialize",
            "program_create or program_import",
            "grammar_help for each unfamiliar form",
            "single-node tools while exploring or repairing",
            "node_apply_batch for one coherent known structure",
            "node_inspect after each coherent local structure",
            "program_validate for a coherent single document",
            "build_target_set for a reusable multi-document program",
            "build_target_validate before a named-target build",
            "branch_merge_preflight after independent agent work",
            "review impact, coverage, and complete affected-target validation",
            "branch_merge with the returned publication_arguments when ready",
            "branch_activity_summary when measuring the workflow",
            "program_build or build_target_build",
            "build_get to inspect immutable provenance and artifact paths",
            "build_diagnostics_page to read mapped errors after a failed build",
            "node_inspect with the failed revision_id before repairing a mapped node",
            "revision_diff_page to compare the failing revision with the current head",
        ],
        "rule": (
            "Keep writes structural and ID-based. Batch only coherent operations; "
            "do not send a nested replacement tree."
        ),
    },
    "write": {
        "tools": {
            "node_create_form": "Attach one list whose first child is the form head.",
            "node_add_atom": "Attach one symbol, string, integer, float, or boolean.",
            "node_set_atom": "Change one atom while preserving its node ID.",
            "node_move": "Move one node to a new parent and position.",
            "node_wrap": "Wrap one node in a new form.",
            "node_delete": "Delete one node and its subtree.",
            "node_apply_batch": (
                "Apply up to 256 flat ordinary node operations as one revision. "
                "Use @aliases for nodes created earlier in the same batch."
            ),
            "branch_merge": (
                "Publish a stable-ID three-way merge. Prefer arguments returned by "
                "branch_merge_preflight so preview, coverage, all affected targets, "
                "and both branch heads are rechecked."
            ),
        },
        "positions": "Child positions are zero-based; omit position to append.",
    },
    "batch": {
        "when": (
            "Use a batch after the intended local structure and grammar forms are "
            "known. Prefer single-node tools for uncertain edits and repairs."
        ),
        "operations": [
            "create_form",
            "add_atom",
            "set_atom",
            "move_node",
            "wrap_node",
            "delete_node",
        ],
        "aliases": (
            "Set as='name' on a created form, atom, or wrapper and reference it as "
            "@name later in the same batch. Use returned stable IDs across batches."
        ),
        "safety": [
            "at most 256 operations",
            "one document and one branch head",
            "expected_revision_id rejects stale agent state",
            "one final structural validation",
            "one immutable revision containing ordered audit rows",
            "any failure rolls back the complete batch",
        ],
    },
    "read": {
        "tools": {
            "node_inspect": (
                "Return an ID-bearing local subtree and grammar hint from the branch head "
                "or an explicit immutable revision_id."
            ),
            "revision_diff_page": (
                "Compare stable nodes between two immutable revisions in bounded pages."
            ),
            "branch_merge_preflight": (
                "Compose exact preview identity, directional impact, coverage, and every "
                "affected surviving target validation into one non-mutating review result."
            ),
            "branch_merge_preview": (
                "Preview conflicts and compact document consequences for two current "
                "branch heads without mutating either branch."
            ),
            "branch_merge_impact": (
                "Map prospective document changes to named build targets in bounded pages "
                "and expose changed program documents with no candidate target coverage."
            ),
            "branch_merge_validate": (
                "Validate one named target from the exact in-memory merge candidate "
                "without publishing a revision or build artifact."
            ),
            "branch_merge_validate_affected": (
                "Validate the complete bounded set of affected surviving targets and "
                "aggregate pass, failure, availability, and coverage evidence."
            ),
            "node_find": "Find stable IDs by form head, atom kind, or value.",
            "program_render": "Render canonical source or an annotated agent view.",
            "program_source_list": (
                "List compiler source documents at a branch head or revision."
            ),
            "branch_history_page": (
                "Read bounded first-parent pages with an explicit continuation."
            ),
            "revision_operations_page": (
                "Read immutable operation targets and payloads in sequence order."
            ),
            "branch_activity_summary": (
                "Measure revisions, operations, merges, authors, and grouping."
            ),
            "grammar_help": "Search the weavec surface corpus for exact examples.",
            "build_get": "Inspect one verified stored build and its artifact paths.",
            "build_diagnostics_page": (
                "Read mapped retained errors without opening server-local files."
            ),
        }
    },
    "history": {
        "page": (
            "Call branch_history_page without start_revision_id for the first page. "
            "When has_more is true, pass next_revision_id as the next start."
        ),
        "bounds": (
            "Page limits are 1..200 and each continuation must be reachable from "
            "the selected branch head."
        ),
        "stability": (
            "Compare branch_head_revision_id across pages when a stable multi-page "
            "read is required; restart if the branch advanced."
        ),
        "audit": (
            "Call revision_operations_page with a revision ID. When has_more is true, "
            "pass next_sequence_number as the next start_sequence_number. Revision "
            "operations are immutable and project-scoped."
        ),
        "inspection": (
            "node_inspect defaults to the selected branch head. Pass revision_id to read "
            "the exact immutable project revision even when it is no longer the branch "
            "head; the response reports both revision_id and branch_head_revision_id."
        ),
        "diff": (
            "revision_diff_page compares one document across two project-owned immutable "
            "revisions. Omit target_revision_id to compare against the selected branch "
            "head. When has_more is true, pass next_index as start_index; immutable "
            "revisions make the continuation stable."
        ),
        "summary": (
            "branch_activity_summary traverses complete first-parent history and "
            "reports operation kinds, single and grouped revisions, merges, authors, "
            "and revisions avoided by grouping."
        ),
        "interpretation": (
            "Metrics are descriptive. Do not maximize batch size merely to reduce "
            "revision count."
        ),
    },
    "merge": {
        "preflight": (
            "branch_merge_preflight is the default review call. It returns exact branch "
            "heads, preview and merged-root identity, bounded directional target impact, "
            "coverage gaps, the complete affected-target validation set, and publication "
            "arguments. It never advances a branch."
        ),
        "preview": (
            "branch_merge_preview binds project, branch direction, common ancestor, and "
            "both current heads into a deterministic preview_id. It never advances a branch."
        ),
        "impact": (
            "branch_merge_impact reports only changes introduced by merging the source "
            "into the current target. It classifies affected named targets and changed "
            "program documents with no surviving candidate target coverage."
        ),
        "validation": (
            "branch_merge_validate inspects one named target. "
            "branch_merge_validate_affected validates every affected surviving target in "
            "deterministic order, aggregates failures, and blocks uncovered documents by "
            "default without starting a compiler."
        ),
        "publish": (
            "When preflight ready_for_publication is true, call publication_tool with "
            "publication_arguments. The complete validation set is repeated, then both "
            "heads are checked in the SQLite write transaction. A preflight is evidence, "
            "not a token that bypasses revalidation."
        ),
        "failures": (
            "Coverage gaps return MERGE_UNCOVERED_DOCUMENTS; unavailable validation returns "
            "MERGE_VALIDATION_UNAVAILABLE; compiler rejection returns "
            "MERGE_VALIDATION_FAILED; changed heads return STALE_MERGE_PREVIEW."
        ),
        "compatibility": (
            "Lower-level preview, impact, single-target validation, all-target validation, "
            "and direct merge calls remain available. Reviewed parallel work should use "
            "branch_merge_preflight and its returned publication arguments."
        ),
    },
    "ids": {
        "rule": "Use returned n_* IDs; never locate code by line number.",
        "lifecycle": [
            "editing an atom preserves its ID",
            "moving a node preserves its ID",
            "new forms and atoms receive new IDs",
            "batch aliases resolve to stable IDs",
            "branches preserve base IDs",
            "annotated renderings expose IDs without changing program meaning",
        ],
    },
    "validation": {
        "structural": "Every committed mutation checks tree shape, unique IDs, and cycles.",
        "grammar": "grammar_help is guidance derived from weavec examples.",
        "single_document": "program_validate invokes weavec --frontend for one document.",
        "multi_document": (
            "build_target_validate pins one target definition and its ordered sources "
            "to one immutable revision before invoking weavec --frontend."
        ),
        "merge_candidate": (
            "branch_merge_preflight and branch_merge_validate_affected invoke the same "
            "authoritative frontend on every affected surviving target from one exact "
            "uncommitted clean merge candidate."
        ),
    },
    "targets": {
        "workflow": [
            "program_source_list to choose source documents",
            "build_target_set to store primary source, ordered additional sources, and target",
            "build_target_validate to validate the exact pinned target",
            "branch_merge_preflight to review impact, coverage, and all affected targets",
            "branch_merge with returned publication_arguments when preflight is ready",
            "build_target_build to compile the same target through weavec build",
            "build_get to inspect provenance, diagnostics, and artifacts",
        ],
        "revision_rule": (
            "Target metadata and every selected source are resolved from the same branch "
            "head, explicit revision, or exact in-memory merge candidate. Source order is "
            "authoritative."
        ),
        "tools": [
            "build_target_set",
            "build_target_list",
            "build_target_get",
            "build_target_delete",
            "build_target_validate",
            "branch_merge_preflight",
            "branch_merge_impact",
            "branch_merge_validate",
            "branch_merge_validate_affected",
            "build_target_build",
        ],
    },
    "builds": {
        "explicit": "program_build compiles an explicit ordered document set.",
        "named": "build_target_build compiles a stored revisioned target.",
        "inspect": (
            "build_get verifies the stored manifest and returns immutable provenance and "
            "artifact paths. build_diagnostics_page returns mapped diagnostic entries in "
            "pages of 1..200 without exposing compiler stdout or stderr."
        ),
        "repair": (
            "On failure, page diagnostics by build ID, pass the returned revision_id to "
            "node_inspect for the mapped stable node_id, compare that revision with the "
            "current branch through revision_diff_page, repair with a structural tool, "
            "then validate and build the new revision."
        ),
        "ownership": (
            "Jacquard owns revision pinning, canonical sources, node maps, and provenance; "
            "weavec owns lowering, LLVM generation, runtime selection, linking, and "
            "publication."
        ),
    },
    "bulk": {
        "tool": "program_import",
        "warning": (
            "Bulk source import exists for migration and fixtures. Agents should use "
            "structural single-node or transactional batch tools for normal construction."
        ),
    },
}


def weave_help(topic: str = "workflow") -> dict[str, Any]:
    """Explain the current editing, validation, and build workflow."""

    return {
        "ok": True,
        "topic": topic,
        "help": _TOPICS.get(topic, _TOPICS["workflow"]),
    }


class _FastMCPServer(Protocol):
    _mcp_server: Any

    def remove_tool(self, name: str) -> None: ...

    def add_tool(
        self,
        function: Any,
        name: str | None = None,
        description: str | None = None,
    ) -> None: ...


def install_runtime_guidance(server: _FastMCPServer) -> None:
    """Replace the legacy help registration used by the extended MCP entrypoint."""

    server._mcp_server.instructions = INSTRUCTIONS
    server.remove_tool("weave_help")
    server.add_tool(
        weave_help,
        name="weave_help",
        description="Explain the structural MCP workflow and identify the right tool.",
    )
