"""Architecture tests for the owned compiler integration package."""

from __future__ import annotations

import ast
from pathlib import Path

from weave_frontend import compiler

ROOT = Path(__file__).parents[1]
FRONTEND = ROOT / "src" / "weave_frontend"
PACKAGE = FRONTEND / "compiler"
IMPLEMENTATION_MODULES = {
    "__init__.py",
    "artifacts.py",
    "bridge.py",
    "capabilities.py",
    "diagnostics.py",
    "inputs.py",
    "io.py",
    "limits.py",
    "manifest.py",
    "validator.py",
}
LEGACY_STEMS = {
    "compiler_artifacts",
    "compiler_bridge",
    "compiler_capabilities",
    "compiler_diagnostics",
    "compiler_inputs",
    "compiler_io",
    "compiler_limits",
    "compiler_manifest",
    "weavec",
}
REMOVED_ADAPTERS = {
    "bounded_process",
    "errors",
    "grammar_help",
    "retained_artifact_io",
    "revision_limits",
    "sexpr",
    "source_map",
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


def test_compiler_package_contains_only_owned_modules() -> None:
    assert {path.name for path in PACKAGE.glob("*.py")} == IMPLEMENTATION_MODULES
    for stem in LEGACY_STEMS:
        assert not (FRONTEND / f"{stem}.py").exists()
    for stem in REMOVED_ADAPTERS:
        assert not (PACKAGE / f"{stem}.py").exists()


def test_repository_contains_no_legacy_compiler_imports() -> None:
    roots = [ROOT / "src", ROOT / "tests", ROOT / "scripts", ROOT / "docs"]
    for directory in roots:
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".md"}:
                continue
            source = path.read_text(encoding="utf-8")
            for stem in LEGACY_STEMS:
                assert ("weave_frontend." + stem) not in source, path
                assert ("from ." + stem + " import") not in source, path


def test_compiler_package_does_not_import_upper_application_layers() -> None:
    for path in PACKAGE.glob("*.py"):
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


def test_application_code_uses_public_compiler_api() -> None:
    for path in FRONTEND.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "from .compiler." not in source, path
        assert "import weave_frontend.compiler." not in source, path
