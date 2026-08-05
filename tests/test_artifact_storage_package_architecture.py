from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "weave_frontend"
STORAGE_PACKAGE = PACKAGE_ROOT / "artifacts" / "storage"


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


def test_storage_implementation_is_not_flattened_into_package_root() -> None:
    for name in ("artifact_storage.py", "artifact_storage_lifecycle.py"):
        assert not (PACKAGE_ROOT / name).exists()
    assert importlib.util.find_spec("weave_frontend.artifact_storage") is None
    assert importlib.util.find_spec("weave_frontend.artifact_storage_lifecycle") is None


def test_cross_domain_code_uses_the_storage_public_boundary() -> None:
    violations: list[str] = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        if STORAGE_PACKAGE in path.parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported = _resolve_import(path, node)
                if imported.startswith("weave_frontend.artifacts.storage."):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("weave_frontend.artifacts.storage."):
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert violations == []


def test_storage_public_boundary_is_explicit() -> None:
    init_path = STORAGE_PACKAGE / "__init__.py"
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
        "ArtifactStorageService",
        "ArtifactLifecycleStorageService",
        "ARTIFACT_STORAGE_REPORT_FORMAT",
        "ARTIFACT_STORAGE_LIFECYCLE_FORMAT",
        "ARTIFACT_STORAGE_ROOT_ID_FORMAT",
        "MAX_ARTIFACT_SCAN_DEPTH",
        "MAX_ARTIFACT_SCAN_ENTRIES",
        "MAX_ARTIFACT_STORAGE_ROOTS",
    }.issubset(exported)


def test_quota_remains_a_separate_consumer_of_storage() -> None:
    quota_path = PACKAGE_ROOT / "artifacts" / "quota" / "service.py"
    tree = ast.parse(quota_path.read_text(encoding="utf-8"), filename=str(quota_path))
    imports = {
        _resolve_import(quota_path, node) for node in tree.body if isinstance(node, ast.ImportFrom)
    }
    assert "weave_frontend.artifacts.storage" in imports
    assert not any(imported.startswith("weave_frontend.artifacts.storage.") for imported in imports)
