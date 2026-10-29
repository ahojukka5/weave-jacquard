from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "weave_frontend"
MERGES_PACKAGE = PACKAGE_ROOT / "merges"

# The flat merge implementations retired by #253. Their only owner is the
# weave_frontend.merges package; these paths must not come back.
RETIRED_FLAT_MERGE_MODULES = (
    "concurrent_merge_policy",
    "merge_candidate_build",
    "merge_impact",
    "merge_policy",
    "merge_preflight",
    "merge_preview",
    "merge_validation",
    "merge_validation_set",
    "metadata_merge_impact",
    "metadata_merge_preview",
    "metadata_selected_merge_train_preview",
    "project_merge_catalog",
    "project_merge_impact_queue",
    "project_merge_queue",
    "selected_merge_preflight_batch",
    "selected_merge_train_preview",
)


def test_merge_implementation_is_not_flattened_into_package_root() -> None:
    for module in RETIRED_FLAT_MERGE_MODULES:
        assert not (PACKAGE_ROOT / f"{module}.py").exists()
        assert importlib.util.find_spec(f"weave_frontend.{module}") is None


def test_no_code_imports_a_retired_flat_merge_module(
    package_import_inventory: tuple[tuple[Path, str, int], ...],
) -> None:
    retired = {f"weave_frontend.{module}" for module in RETIRED_FLAT_MERGE_MODULES}
    violations = [
        f"{path.relative_to(ROOT)}:{lineno}"
        for path, imported, lineno in package_import_inventory
        if imported in retired or any(imported.startswith(f"{name}.") for name in retired)
    ]
    assert violations == []


def test_tests_do_not_import_a_retired_flat_merge_module() -> None:
    retired = set(RETIRED_FLAT_MERGE_MODULES)
    violations = []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                parts = node.module.split(".")
                if parts[0] != "weave_frontend":
                    continue
                if (len(parts) > 1 and parts[1] in retired) or (
                    len(parts) == 1 and any(alias.name in retired for alias in node.names)
                ):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    if parts[0] == "weave_frontend" and len(parts) > 1 and parts[1] in retired:
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert violations == []
