from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from weave_frontend import SExpressionWorkspace


def pytest_pycollect_makeitem(
    collector: pytest.Collector,
    name: str,
    obj: Any,
) -> list[pytest.Item] | None:
    """Do not treat imported production classes named ``Test*`` as test suites."""

    module = getattr(obj, "__module__", "")
    if name.startswith("Test") and module.startswith("weave_frontend."):
        return []
    return None


@pytest.fixture
def sexpr_workspace(tmp_path):
    with SExpressionWorkspace(tmp_path / "sexpr.db") as value:
        value.initialize("sexpr-demo")
        yield value


@pytest.fixture(scope="session")
def package_python_sources() -> tuple[tuple[Path, str], ...]:
    """Read package Python sources once for repository architecture checks."""

    root = Path(__file__).resolve().parents[1]
    package_root = root / "src" / "weave_frontend"
    return tuple(
        (path, path.read_text(encoding="utf-8"))
        for path in sorted(package_root.rglob("*.py"))
    )


@pytest.fixture(scope="session")
def package_import_inventory(
    package_python_sources: tuple[tuple[Path, str], ...],
) -> tuple[tuple[Path, str, int], ...]:
    """Parse package imports once for cross-domain boundary checks."""

    root = Path(__file__).resolve().parents[1]
    source_root = root / "src"
    imports: list[tuple[Path, str, int]] = []

    def module_name(path: Path) -> str:
        relative = path.relative_to(source_root).with_suffix("")
        return ".".join(relative.parts)

    def resolve_import(path: Path, node: ast.ImportFrom) -> str:
        module = node.module or ""
        if node.level == 0:
            return module
        package = module_name(path).split(".")[:-1]
        keep = len(package) - (node.level - 1)
        prefix = package[:keep]
        if module:
            prefix.extend(module.split("."))
        return ".".join(prefix)

    for path, source in package_python_sources:
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imports.append((path, resolve_import(path, node), node.lineno))
            elif isinstance(node, ast.Import):
                imports.extend((path, alias.name, node.lineno) for alias in node.names)

    return tuple(imports)
