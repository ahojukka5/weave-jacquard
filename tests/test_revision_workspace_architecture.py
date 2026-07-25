from __future__ import annotations

import inspect
from pathlib import Path

import weave_frontend
from weave_frontend.service import MergeResult, RevisionWorkspace
from weave_frontend.sexpr_service import SExpressionWorkspace


_TYPED_METHODS = {
    "add_import",
    "create_function",
    "create_module",
    "find_symbols",
    "inspect_function",
    "insert_statement",
    "replace_node",
    "validate",
}


def test_production_workspace_inherits_only_revision_base() -> None:
    assert SExpressionWorkspace.__mro__[1] is RevisionWorkspace
    assert _TYPED_METHODS.isdisjoint(dir(SExpressionWorkspace))

    source = inspect.getsource(RevisionWorkspace)
    assert "from .grammar" not in source
    assert "from .renderer" not in source
    assert "from .model" not in source
    assert "validate_function" not in source


def test_legacy_typed_api_is_not_exported() -> None:
    assert not hasattr(weave_frontend, "Workspace")
    assert not hasattr(weave_frontend, "MutationResult")
    assert not hasattr(weave_frontend, "SymbolSummary")
    assert weave_frontend.MergeResult is MergeResult


def test_legacy_console_script_is_removed() -> None:
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    content = pyproject.read_text(encoding="utf-8")

    assert "weave-front =" not in content
    assert 'weave-mcp = "weave_frontend.mcp_build:main"' in content
    assert 'weave-build = "weave_frontend.build_cli:main"' in content


def test_merge_result_remains_stable(sexpr_workspace) -> None:
    program = sexpr_workspace.create_program(
        "sexpr-demo",
        "main",
        "main.weave",
        program_name="merge-result",
    )
    root_id = program["node_id"]
    sexpr_workspace.create_branch("sexpr-demo", "agent")
    sexpr_workspace.create_form(
        "sexpr-demo",
        "agent",
        "main.weave",
        root_id,
        "fn",
    )

    result = sexpr_workspace.merge(
        "sexpr-demo",
        target_branch="main",
        source_branch="agent",
    )

    assert isinstance(result, MergeResult)
    assert result.target_branch == "main"
    assert result.source_branch == "agent"
    assert result.changed_symbols == ("main.weave",)
    assert sexpr_workspace.branch_head("sexpr-demo", "main") == result.revision_id
