"""Architecture tests for the owned compiler integration package."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

from weave_frontend import compiler

ROOT = Path(__file__).parents[1] / "src" / "weave_frontend"
COMPATIBILITY_MODULES = {
    "compiler_artifacts": "compiler_artifacts",
    "compiler_bridge": "compiler_bridge",
    "compiler_capabilities": "compiler_capabilities",
    "compiler_diagnostics": "compiler_diagnostics",
    "compiler_inputs": "compiler_inputs",
    "compiler_io": "compiler_io",
    "compiler_limits": "compiler_limits",
    "compiler_manifest": "compiler_manifest",
    "weavec": "weavec",
}
FORBIDDEN_UPPER_LAYERS = {
    "artifact_quota",
    "build_targets",
    "database",
    "database_backup",
    "mcp_server",
    "runtime_container",
    "service",
    "snapshot_codec",
    "verified_workspace",
}


def test_compiler_package_exposes_one_public_surface() -> None:
    expected = {
        "CompilerBridge",
        "WeavecCapabilities",
        "WeavecValidator",
        "CapabilityAwareWeavecValidator",
        "CapabilityGrammarIndex",
        "collect_build_diagnostics",
        "validate_compiler_manifest",
        "read_bounded_json",
    }
    assert expected <= set(compiler.__all__)
    for name in expected:
        assert getattr(compiler, name) is not None


def test_flat_compiler_paths_alias_owned_modules() -> None:
    for compatibility_name, implementation_name in COMPATIBILITY_MODULES.items():
        compatibility = importlib.import_module(f"weave_frontend.{compatibility_name}")
        implementation = importlib.import_module(
            f"weave_frontend.compiler.{implementation_name}"
        )
        assert compatibility is implementation


def test_flat_compiler_files_contain_no_implementation() -> None:
    for name in COMPATIBILITY_MODULES:
        path = ROOT / f"{name}.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        definitions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        assert definitions == [], path
        assert len(source.splitlines()) <= 24, path
        assert "sys.modules[__name__] = _implementation" in source


def test_compiler_package_does_not_import_upper_application_layers() -> None:
    package = ROOT / "compiler"
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
                if node.level >= 2 and node.module:
                    top = node.module.split(".", 1)[0]
                    assert top not in FORBIDDEN_UPPER_LAYERS, (path, top)
            else:
                continue
            for name in names:
                assert "weavec0" not in name
                assert "weavec1" not in name
                assert "weave_bootstrap" not in name
                assert "weave-bootstrap" not in name


def test_application_adapters_use_public_compiler_api() -> None:
    quota_source = (ROOT / "quota_aware_compiler_bridge.py").read_text(
        encoding="utf-8"
    )
    workspace_source = (ROOT / "verified_workspace.py").read_text(
        encoding="utf-8"
    )
    assert "from .compiler import CompilerBridge as _CompilerBridge" in quota_source
    assert "from .compiler import WeavecCapabilities" in quota_source
    assert "from .compiler import (" in workspace_source
    assert "from .compiler_capabilities import" not in workspace_source
    assert "from .weavec import" not in workspace_source
