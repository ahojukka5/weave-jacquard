"""Model Context Protocol server for atomic Weave program construction."""

from __future__ import annotations

import atexit
import os
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from functools import lru_cache
from typing import Any

from mcp.server.fastmcp import FastMCP

from .errors import ConflictError, ValidationError, WeaveFrontendError
from .sexpr_service import SExpressionWorkspace

INSTRUCTIONS = """
Build Weave programs atomically. Read larger annotated subtrees when useful, but
write one form, atom, edge, or move at a time. Call grammar_help before using an
unfamiliar Weave form. Every mutation returns stable node IDs and a new immutable
revision. Call program_validate after completing a coherent program unit; the
configured weavec frontend is the authoritative language validator.
""".strip()

mcp = FastMCP("weave-mcp", instructions=INSTRUCTIONS)


@lru_cache(maxsize=1)
def workspace() -> SExpressionWorkspace:
    return SExpressionWorkspace(
        os.environ.get("WEAVE_DB_PATH", "weave.db"),
        weavec_source_root=os.environ.get("WEAVEC_SOURCE_ROOT"),
        weavec_binary=os.environ.get("WEAVEC_BIN"),
    )


@atexit.register
def _close_workspace() -> None:
    if workspace.cache_info().currsize:
        workspace().close()
        workspace.cache_clear()


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def _result(call: Callable[[], Any]) -> dict[str, Any]:
    try:
        return {"ok": True, "result": _jsonable(call())}
    except ValidationError as exc:
        return {"ok": False, "error": exc.as_dict()}
    except ConflictError as exc:
        return {
            "ok": False,
            "error": {"code": "MERGE_CONFLICT", "conflicts": exc.conflicts},
        }
    except WeaveFrontendError as exc:
        return {
            "ok": False,
            "error": {"code": type(exc).__name__, "message": str(exc)},
        }


@mcp.tool()
def weave_help(topic: str = "workflow") -> dict[str, Any]:
    """Explain the atomic MCP workflow and identify the right tool for a task."""
    topics: dict[str, Any] = {
        "workflow": {
            "steps": [
                "project_initialize",
                "program_create",
                "grammar_help for each unfamiliar form",
                "node_create_form and node_add_atom repeatedly",
                "node_inspect after each coherent local structure",
                "program_validate when the program is complete",
                "branch_merge after independent agent work",
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
                "grammar_help": "Search the weavec surface corpus for exact examples.",
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
            "authoritative": "program_validate invokes weavec --frontend.",
        },
        "bulk": {
            "tool": "program_import",
            "warning": (
                "Bulk source import exists for migration and fixtures. Agents should "
                "prefer atomic node tools for normal construction."
            ),
        },
    }
    return {"ok": True, "topic": topic, "help": topics.get(topic, topics["workflow"])}


@mcp.tool()
def grammar_help(
    form: str | None = None,
    query: str | None = None,
    parent_form: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """Find observed Weave grammar forms and examples from the surface corpus."""
    return _result(
        lambda: workspace().grammar_help(
            form=form,
            query=query,
            parent_form=parent_form,
            limit=limit,
        )
    )


@mcp.tool()
def project_initialize(project: str, author: str = "agent") -> dict[str, Any]:
    """Create a versioned Weave project with an empty main branch."""
    return _result(lambda: workspace().initialize(project, author=author))


@mcp.tool()
def branch_create(
    project: str,
    branch: str,
    from_branch: str = "main",
) -> dict[str, Any]:
    """Create an independent agent branch from an existing branch head."""
    return _result(
        lambda: workspace().create_branch(project, branch, from_branch=from_branch)
    )


@mcp.tool()
def branch_list(project: str) -> dict[str, Any]:
    """List branch heads for a project."""
    return _result(lambda: workspace().list_branches(project))


@mcp.tool()
def branch_history(
    project: str,
    branch: str = "main",
    limit: int = 50,
) -> dict[str, Any]:
    """List immutable revisions reachable from a branch head."""
    return _result(lambda: workspace().list_history(project, branch, limit=limit))


@mcp.tool()
def branch_merge(
    project: str,
    target_branch: str,
    source_branch: str,
) -> dict[str, Any]:
    """Three-way merge stable node IDs and validate the resulting tree."""
    return _result(
        lambda: workspace().merge(
            project,
            target_branch=target_branch,
            source_branch=source_branch,
        )
    )


@mcp.tool()
def program_create(
    project: str,
    branch: str,
    document: str,
    program_name: str,
    version: str = "0.1",
) -> dict[str, Any]:
    """Create the program, name, and version forms and return the root ID."""
    return _result(
        lambda: workspace().create_program(
            project,
            branch,
            document,
            program_name=program_name,
            version=version,
        )
    )


@mcp.tool()
def program_import(
    project: str,
    branch: str,
    document: str,
    source: str,
    replace: bool = False,
) -> dict[str, Any]:
    """Import source for migration; prefer atomic node tools for agent writing."""
    return _result(
        lambda: workspace().import_program(
            project,
            branch,
            document,
            source,
            replace=replace,
        )
    )


@mcp.tool()
def program_list(project: str, branch: str = "main") -> dict[str, Any]:
    """List program documents and their root node IDs."""
    return _result(lambda: workspace().list_documents(project, branch))


@mcp.tool()
def node_create_form(
    project: str,
    branch: str,
    document: str,
    parent_id: str,
    head: str,
    position: int | None = None,
) -> dict[str, Any]:
    """Create and attach one form such as fn, params, while, or return."""
    return _result(
        lambda: workspace().create_form(
            project,
            branch,
            document,
            parent_id,
            head,
            position=position,
        )
    )


@mcp.tool()
def node_add_atom(
    project: str,
    branch: str,
    document: str,
    parent_id: str,
    kind: str,
    value: Any,
    position: int | None = None,
) -> dict[str, Any]:
    """Attach one atom: symbol, string, integer, float, or boolean."""
    return _result(
        lambda: workspace().add_atom(
            project,
            branch,
            document,
            parent_id,
            kind,
            value,
            position=position,
        )
    )


@mcp.tool()
def node_set_atom(
    project: str,
    branch: str,
    document: str,
    node_id: str,
    value: Any,
) -> dict[str, Any]:
    """Change one atom value while preserving its stable node ID."""
    return _result(
        lambda: workspace().set_atom(project, branch, document, node_id, value)
    )


@mcp.tool()
def node_delete(
    project: str,
    branch: str,
    document: str,
    node_id: str,
) -> dict[str, Any]:
    """Delete one node and its contained subtree."""
    return _result(lambda: workspace().delete_node(project, branch, document, node_id))


@mcp.tool()
def node_move(
    project: str,
    branch: str,
    document: str,
    node_id: str,
    new_parent_id: str,
    position: int | None = None,
) -> dict[str, Any]:
    """Move one node to a list parent without changing its stable ID."""
    return _result(
        lambda: workspace().move_node(
            project,
            branch,
            document,
            node_id,
            new_parent_id,
            position=position,
        )
    )


@mcp.tool()
def node_wrap(
    project: str,
    branch: str,
    document: str,
    node_id: str,
    head: str,
) -> dict[str, Any]:
    """Wrap one existing node in a newly created form."""
    return _result(lambda: workspace().wrap_node(project, branch, document, node_id, head))


@mcp.tool()
def node_inspect(
    project: str,
    branch: str,
    document: str,
    node_id: str,
    depth: int = 3,
) -> dict[str, Any]:
    """Inspect a local ID-bearing subtree without loading the full program."""
    return _result(
        lambda: workspace().inspect_node(
            project,
            branch,
            document,
            node_id,
            depth=depth,
        )
    )


@mcp.tool()
def node_find(
    project: str,
    branch: str,
    document: str,
    head: str | None = None,
    kind: str | None = None,
    value: Any | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Find exact node IDs by form head, atom kind, or atom value."""
    return _result(
        lambda: workspace().find_nodes(
            project,
            branch,
            document,
            head=head,
            kind=kind,
            value=value,
            limit=limit,
        )
    )


@mcp.tool()
def program_render(
    project: str,
    branch: str,
    document: str,
    annotated: bool = True,
    annotate_atoms: bool = False,
) -> dict[str, Any]:
    """Render canonical Weave or an agent view exposing stable node IDs."""
    return _result(
        lambda: {
            "document": document,
            "annotated": annotated,
            "source": workspace().render(
                project,
                branch,
                document,
                annotated=annotated,
                annotate_atoms=annotate_atoms,
            ),
        }
    )


@mcp.tool()
def program_validate(
    project: str,
    branch: str,
    document: str,
) -> dict[str, Any]:
    """Validate a completed program with the configured weavec frontend."""
    return _result(lambda: workspace().validate_program(project, branch, document))


@mcp.tool()
def context_add(
    project: str,
    branch: str,
    scope_kind: str,
    scope_name: str,
    title: str,
    body: str,
) -> dict[str, Any]:
    """Version a design rule, contract, or interface note with the branch."""
    return _result(
        lambda: workspace().add_context(
            project,
            branch,
            scope_kind=scope_kind,
            scope_name=scope_name,
            title=title,
            body=body,
        )
    )


@mcp.tool()
def context_get(
    project: str,
    branch: str,
    scope_name: str,
) -> dict[str, Any]:
    """Retrieve design context pinned to the current branch revision."""
    return _result(
        lambda: workspace().get_context(
            project,
            branch,
            scope_name=scope_name,
        )
    )


def main() -> None:
    """Run the server using the standard MCP stdio transport."""
    mcp.run()


if __name__ == "__main__":
    main()
