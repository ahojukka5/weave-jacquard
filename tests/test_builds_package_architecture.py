from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "weave_frontend"
BUILDS_PACKAGE = PACKAGE_ROOT / "builds"


def test_build_catalog_implementation_is_not_flattened_into_package_root() -> None:
    for module in (
        "build_discovery",
        "build_inspection",
        "build_target_validation",
        "build_targets",
        "concurrent_build_targets",
        "metadata_build_targets",
        "target_validation",
        "verified_build_discovery",
    ):
        assert not (PACKAGE_ROOT / f"{module}.py").exists()
        assert importlib.util.find_spec(f"weave_frontend.{module}") is None


def test_cross_domain_code_uses_builds_public_boundary(
    package_import_inventory: tuple[tuple[Path, str, int], ...],
) -> None:
    violations = [
        f"{path.relative_to(ROOT)}:{lineno}"
        for path, imported, lineno in package_import_inventory
        if BUILDS_PACKAGE not in path.parents
        and imported.startswith("weave_frontend.builds.")
    ]
    assert violations == []


def test_builds_public_boundary_is_explicit() -> None:
    init_path = BUILDS_PACKAGE / "__init__.py"
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
        "BUILD_CATALOG_FORMAT",
        "BUILD_LIST_FORMAT",
        "BUILD_TARGET_PREFIX",
        "BuildDiscoveryService",
        "BuildInspectionService",
        "BuildTargetRegistry",
        "BuildTargetValidator",
        "ConcurrentBuildTargetRegistry",
        "MAX_BUILD_CATALOG_ENTRIES",
        "MAX_BUILD_LIST_PAGE_SIZE",
        "MAX_DIAGNOSTIC_PAGE_SIZE",
        "MetadataBuildTargetRegistry",
        "build_target_references",
        "validate_build_target_references",
    }.issubset(exported)
