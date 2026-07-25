"""Runtime guidance exposed to coding agents through the MCP server."""

from __future__ import annotations

from typing import Any, Protocol


INSTRUCTIONS = """
Build Weave programs atomically. Read larger annotated subtrees when useful, but
write one form, atom, edge, or move at a time. Call grammar_help before using an
unfamiliar Weave form. Every mutation returns stable node IDs and a new immutable
revision. Use program_validate for a coherent single document. For a
multi-document program, define a named target and use build_target_validate so
the target metadata and ordered sources are validated from one pinned revision.
Build through program_build or build_target_build and inspect the immutable
result with build_get.
""".strip()


_TOPICS: dict[str, dict[str, Any]] = {
    "workflow": {
        "steps": [
            "project_initialize",
            "program_create or program_import",
            "grammar_help for each unfamiliar form",
            "node_create_form and node_add_atom repeatedly",
            "node_inspect after each coherent local structure",
            "program_validate for a coherent single document",
            "build_target_set for a reusable multi-document program",
            "build_target_validate before a named-target build",
            "branch_merge after independent agent work",
            "program_build or build_target_build",
            "build_get to inspect immutable artifacts and diagnostics",
        ],
        "rule": "Prefer atomic writes. Do not generate a large JSON subtree.",
    },
    "write": {
        "tools": {
            "node_create_form": "Attach one list whose first child is the form head.",
            "node_add_atom": "Attach one symbol, string, integer, float, or boolean.",
            "node_set_atom": "Change one atom while preserving its node ID.",
            "node_move": "Move one node to a new parent and position.",
            "node_wrap": "Wrap one node in a new form.",
            "node_delete": "Delete one node and its subtree.",
        },
        "positions": "Child positions are zero-based; omit position to append.",
    },
    "read": {
        "tools": {
            "node_inspect": "Return an ID-bearing local subtree and grammar hint.",
            "node_find": "Find forms or atoms by head, kind, or value.",
            "program_render": "Render canonical source or an annotated agent view.",
            "program_source_list": "List compiler source documents at a branch head or revision.",
            "grammar_help": "Search the weavec surface corpus for exact examples.",
            "build_get": "Inspect one stored build and its immutable artifact paths.",
        }
    },
    "ids": {
        "rule": "Use returned n_* IDs; never locate code by line number.",
        "lifecycle": [
            "editing an atom preserves its ID",
            "moving a node preserves its ID",
            "new forms and atoms receive new IDs",
            "branches preserve base IDs",
            "annotated renderings expose IDs without changing program meaning",
        ],
    },
    "validation": {
        "structural": "Every mutation checks tree shape, unique IDs, and cycles.",
        "grammar": "grammar_help is guidance derived from weavec examples.",
        "single_document": "program_validate invokes weavec --frontend for one document.",
        "multi_document": (
            "build_target_validate pins one target definition and its ordered sources "
            "to one immutable revision before invoking weavec --frontend."
        ),
    },
    "targets": {
        "workflow": [
            "program_source_list to choose source documents",
            "build_target_set to store primary source, ordered additional sources, and target",
            "build_target_validate to validate the exact pinned target",
            "build_target_build to compile the same target through weavec build",
            "build_get to inspect provenance, diagnostics, and artifacts",
        ],
        "revision_rule": (
            "Target metadata and every selected source are resolved from the same branch head "
            "or explicit revision. Source order is authoritative."
        ),
        "tools": [
            "build_target_set",
            "build_target_list",
            "build_target_get",
            "build_target_delete",
            "build_target_validate",
            "build_target_build",
        ],
    },
    "builds": {
        "explicit": "program_build compiles an explicit ordered document set.",
        "named": "build_target_build compiles a stored revisioned target.",
        "inspect": "build_get returns the stored manifest and artifact paths.",
        "ownership": (
            "weave_frontend owns revision pinning, canonical sources, node maps, and provenance; "
            "weavec owns lowering, LLVM generation, runtime selection, linking, and publication."
        ),
    },
    "bulk": {
        "tool": "program_import",
        "warning": (
            "Bulk source import exists for migration and fixtures. Agents should "
            "prefer atomic node tools for normal construction."
        ),
    },
}


def weave_help(topic: str = "workflow") -> dict[str, Any]:
    """Explain the current atomic editing, validation, and build workflow."""

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
        description="Explain the atomic MCP workflow and identify the right tool for a task.",
    )
