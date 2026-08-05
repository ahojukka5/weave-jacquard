from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "weave_frontend"
RUNTIME_PACKAGE = PACKAGE_ROOT / "runtime"


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


def test_runtime_implementation_is_not_flattened_into_package_root() -> None:
    old_modules = (
        "application_runtime_binding",
        "quota_aware_compiler_bridge",
        "quota_aware_test_batches",
        "quota_aware_test_runs",
        "quota_aware_tested_merge_attestations",
        "runtime_config",
        "runtime_container",
        "runtime_sandbox",
    )
    for module in old_modules:
        assert not (PACKAGE_ROOT / f"{module}.py").exists()
        assert importlib.util.find_spec(f"weave_frontend.{module}") is None


def test_cross_domain_code_uses_the_runtime_public_boundary() -> None:
    violations: list[str] = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        if RUNTIME_PACKAGE in path.parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported = _resolve_import(path, node)
                if imported.startswith("weave_frontend.runtime."):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("weave_frontend.runtime."):
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert violations == []


def test_runtime_public_boundary_is_explicit() -> None:
    init_path = RUNTIME_PACKAGE / "__init__.py"
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
        "CompilerBridge",
        "RuntimeBubblewrapSandbox",
        "RuntimeConfig",
        "RuntimeServices",
        "TestBatchService",
        "TestRunService",
        "TestedMergeAttestationService",
        "bind_application_runtime",
        "runtime_config",
        "runtime_service",
        "runtime_services",
    }.issubset(exported)


def test_runtime_constructs_concrete_publishers_without_upgrade_adapters() -> None:
    publication_path = RUNTIME_PACKAGE / "publication.py"
    publication = publication_path.read_text(encoding="utf-8")
    container = (RUNTIME_PACKAGE / "container.py").read_text(encoding="utf-8")
    repository_python = "\n".join(
        path.read_text(encoding="utf-8") for path in PACKAGE_ROOT.rglob("*.py")
    )

    assert "install_quota_aware_compiler_bridge" not in repository_python
    assert ".__class__" not in publication
    assert "from .publication import CompilerBridge" in container
    assert "bridge = CompilerBridge(" in container


def test_runtime_publication_dependency_direction() -> None:
    publication_path = RUNTIME_PACKAGE / "publication.py"
    tree = ast.parse(
        publication_path.read_text(encoding="utf-8"),
        filename=str(publication_path),
    )
    imports = {
        _resolve_import(publication_path, node)
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
    }
    assert "weave_frontend.artifacts.quota" in imports
    assert "weave_frontend.compiler" in imports
    assert "weave_frontend.test_batches" in imports
    assert "weave_frontend.test_runs" in imports
    assert "weave_frontend.tested_merge_attestations" in imports

    for relative in (
        "compiler",
        "test_batches.py",
        "test_runs.py",
        "tested_merge_attestations.py",
    ):
        path = PACKAGE_ROOT / relative
        paths = path.rglob("*.py") if path.is_dir() else (path,)
        for source_path in paths:
            source = source_path.read_text(encoding="utf-8")
            assert "weave_frontend.runtime" not in source
            assert "from .runtime" not in source
