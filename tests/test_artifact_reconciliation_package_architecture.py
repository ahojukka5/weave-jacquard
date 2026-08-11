from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "weave_frontend"
RECONCILIATION_PACKAGE = PACKAGE_ROOT / "artifacts" / "reconciliation"


def test_reconciliation_implementation_is_not_flattened_into_package_root() -> None:
    for name in (
        "artifact_reconciliation.py",
        "artifact_reachability.py",
        "artifact_reconciliation_cli.py",
    ):
        assert not (PACKAGE_ROOT / name).exists()
    assert importlib.util.find_spec("weave_frontend.artifact_reconciliation") is None
    assert importlib.util.find_spec("weave_frontend.artifact_reachability") is None
    assert importlib.util.find_spec("weave_frontend.artifact_reconciliation_cli") is None


def test_cross_domain_code_uses_the_reconciliation_public_boundary(
    package_import_inventory: tuple[tuple[Path, str, int], ...],
) -> None:
    violations = [
        f"{path.relative_to(ROOT)}:{lineno}"
        for path, imported, lineno in package_import_inventory
        if RECONCILIATION_PACKAGE not in path.parents
        and imported.startswith("weave_frontend.artifacts.reconciliation.")
    ]
    assert violations == []


def test_reconciliation_public_boundary_is_explicit() -> None:
    init_path = RECONCILIATION_PACKAGE / "__init__.py"
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
        "ArtifactReconciliationService",
        "RetainedArtifactFamily",
        "RetainedArtifactInventoryService",
        "ARTIFACT_RECONCILIATION_FORMAT",
        "RETAINED_ARTIFACT_INVENTORY_FORMAT",
    }.issubset(exported)
    assert {"build_parser", "generate_report", "main"}.isdisjoint(exported)
