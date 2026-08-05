from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "weave_frontend"
RETENTION_PACKAGE = PACKAGE_ROOT / "artifacts" / "retention"


def _module_name(path: Path) -> str:
    relative = path.relative_to(ROOT / "src").with_suffix("")
    return ".".join(relative.parts)


def _resolve_import(path: Path, node: ast.ImportFrom) -> str:
    module = node.module or ""
    if node.level == 0:
        return module
    package = _module_name(path).split(".")[:-1]
    keep = len(package) - (node.level - 1)
    prefix = package[:keep]
    if module:
        prefix.extend(module.split("."))
    return ".".join(prefix)


def test_retention_implementation_is_not_flattened_into_package_root() -> None:
    assert list(PACKAGE_ROOT.glob("artifact_retention*.py")) == []
    assert importlib.util.find_spec("weave_frontend.artifact_retention") is None
    assert importlib.util.find_spec("weave_frontend.artifact_retention_policy") is None


def test_cross_domain_code_uses_the_retention_public_boundary() -> None:
    violations: list[str] = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        if RETENTION_PACKAGE in path.parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported = _resolve_import(path, node)
                if imported.startswith("weave_frontend.artifacts.retention."):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("weave_frontend.artifacts.retention."):
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
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
