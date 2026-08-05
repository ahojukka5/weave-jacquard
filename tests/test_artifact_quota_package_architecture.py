from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "weave_frontend"
QUOTA_PACKAGE = PACKAGE_ROOT / "artifacts" / "quota"


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


def test_quota_implementation_is_not_flattened_into_package_root() -> None:
    for name in ("artifact_quota.py", "quota_publication.py"):
        assert not (PACKAGE_ROOT / name).exists()
    assert importlib.util.find_spec("weave_frontend.artifact_quota") is None
    assert importlib.util.find_spec("weave_frontend.quota_publication") is None


def test_cross_domain_code_uses_the_quota_public_boundary() -> None:
    violations: list[str] = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        if QUOTA_PACKAGE in path.parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported = _resolve_import(path, node)
                if imported.startswith("weave_frontend.artifacts.quota."):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("weave_frontend.artifacts.quota."):
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert violations == []


def test_quota_public_boundary_is_explicit() -> None:
    init_path = QUOTA_PACKAGE / "__init__.py"
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
        "ArtifactQuotaService",
        "QuotaPublicationLockMixin",
        "artifact_quota_admission",
        "artifact_quota_publication_lock",
        "parse_artifact_quota",
        "ARTIFACT_QUOTA_ENV",
        "ARTIFACT_QUOTA_POLICY_FORMAT",
        "ARTIFACT_QUOTA_REPORT_FORMAT",
    }.issubset(exported)


def test_quota_internal_dependency_direction() -> None:
    admission = ast.parse((QUOTA_PACKAGE / "admission.py").read_text(encoding="utf-8"))
    publication = ast.parse((QUOTA_PACKAGE / "publication.py").read_text(encoding="utf-8"))
    service = ast.parse((QUOTA_PACKAGE / "service.py").read_text(encoding="utf-8"))

    admission_imports = {
        _resolve_import(QUOTA_PACKAGE / "admission.py", node)
        for node in admission.body
        if isinstance(node, ast.ImportFrom)
    }
    publication_imports = {
        _resolve_import(QUOTA_PACKAGE / "publication.py", node)
        for node in publication.body
        if isinstance(node, ast.ImportFrom)
    }
    service_imports = {
        _resolve_import(QUOTA_PACKAGE / "service.py", node)
        for node in service.body
        if isinstance(node, ast.ImportFrom)
    }

    assert "weave_frontend.artifacts.quota.service" in admission_imports
    assert "weave_frontend.artifacts.quota.admission" in publication_imports
    assert "weave_frontend.artifacts.storage" in service_imports
    assert not any(
        imported.startswith("weave_frontend.artifacts.storage.") for imported in service_imports
    )
