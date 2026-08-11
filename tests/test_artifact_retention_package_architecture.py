from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "weave_frontend"
RETENTION_PACKAGE = PACKAGE_ROOT / "artifacts" / "retention"


def test_retention_implementation_is_not_flattened_into_package_root() -> None:
    assert list(PACKAGE_ROOT.glob("artifact_retention*.py")) == []
    assert importlib.util.find_spec("weave_frontend.artifact_retention") is None
    assert importlib.util.find_spec("weave_frontend.artifact_retention_policy") is None


def test_cross_domain_code_uses_the_retention_public_boundary(
    package_import_inventory: tuple[tuple[Path, str, int], ...],
) -> None:
    violations = [
        f"{path.relative_to(ROOT)}:{lineno}"
        for path, imported, lineno in package_import_inventory
        if RETENTION_PACKAGE not in path.parents
        and imported.startswith("weave_frontend.artifacts.retention.")
    ]
    assert violations == []


def test_retention_public_boundary_is_explicit() -> None:
    init_path = RETENTION_PACKAGE / "__init__.py"
    tree = ast.parse(init_path.read_text(encoding="utf-8"), filename=str(init_path))
    assignments = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
    ]
    assert len(assignments) == 1
    assert isinstance(assignments[0].value, ast.List)
    exported = [
        item.value
        for item in assignments[0].value.elts
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    ]
    assert exported == sorted(set(exported))
    assert {
        "ArtifactRetentionPlanner",
        "ArtifactRetentionAccountant",
        "ArtifactRetentionCatalog",
        "ARTIFACT_RETENTION_POLICY_FORMAT",
        "ARTIFACT_RETENTION_PLAN_FORMAT",
        "MAX_RETENTION_POLICY_BYTES",
        "load_policy",
    }.issubset(exported)
    assert {
        "build_parser",
        "generate_plan",
        "main",
    }.isdisjoint(exported)
