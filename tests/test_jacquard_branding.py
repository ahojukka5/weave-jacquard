from __future__ import annotations

import tomllib
from pathlib import Path

import weave_jacquard
from weave_frontend import SExpressionWorkspace as InternalSExpressionWorkspace

ROOT = Path(__file__).parents[1]


def test_public_jacquard_namespace_exports_safe_workspace(tmp_path: Path) -> None:
    public = weave_jacquard.SExpressionWorkspace

    assert public is not InternalSExpressionWorkspace
    assert issubclass(public, InternalSExpressionWorkspace)
    assert not hasattr(public, "checkout")
    assert weave_jacquard.JacquardError is not None

    with public(tmp_path / "public.db") as workspace:
        assert not hasattr(workspace, "checkout")
        assert callable(workspace.create_branch_at_revision)


def test_distribution_and_entry_points_use_jacquard_name() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["name"] == "weave-jacquard"
    assert metadata["project"]["urls"]["Repository"].endswith("/weave-jacquard")
    assert metadata["project"]["scripts"] == {
        "weave-mcp": "weave_jacquard.mcp_build:main",
        "weave-build": "weave_jacquard.build_cli:main",
    }


def test_readme_presents_jacquard_as_the_product() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert readme.startswith("# Jacquard\n")
    assert "weave-jacquard" in readme
    assert "weave_jacquard" in readme
    assert "# weave_frontend" not in readme
