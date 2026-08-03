from __future__ import annotations

import ast
from pathlib import Path

_CONTEXT_OWNED_CAPABILITY_MODULES = (
    "mcp_concurrent_nodes.py",
    "mcp_test_targets.py",
    "mcp_merge_test_impact.py",
    "mcp_merge_candidate_test_runs.py",
    "mcp_tested_merge_attestations.py",
    "mcp_revert.py",
    "mcp_database_backup.py",
    "mcp_artifact_storage.py",
)


def test_context_owned_capabilities_have_no_module_local_installers() -> None:
    source_root = Path(__file__).parents[1] / "src" / "weave_frontend"

    for filename in _CONTEXT_OWNED_CAPABILITY_MODULES:
        tree = ast.parse(
            (source_root / filename).read_text(encoding="utf-8"),
            filename=filename,
        )
        installer_definitions = [
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "install_capability"
        ]
        installer_calls = [
            node
            for node in tree.body
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "install_capability"
        ]

        assert installer_definitions == []
        assert installer_calls == []
