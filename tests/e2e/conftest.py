from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

_CAPABILITY_TEST_FILES = {
    "test_real_mcp_revision_evidence.py": True,
    "test_real_mcp_selected_merge_preflight_batch.py": False,
}


def _registry() -> dict[str, Any]:
    return {
        "format": "weavec-capabilities-v1",
        "schema_id": "urn:weavec:schema:capabilities:v1",
        "schema_version": 1,
        "compiler": {
            "name": "weavec",
            "version": "test-fake",
            "public_variant": "final",
        },
        "language": {
            "name": "Weave",
            "surface_version": "weave-surface-v1",
            "grammar_id": "weave-surface-grammar-v1",
            "syntax": "s-expression",
            "case_sensitive": True,
            "wir_core_version": 2,
        },
        "protocols": [
            {
                "id": "weavec-capabilities-v1",
                "version": 1,
                "kind": "capability-registry",
            },
            {
                "id": "weavec-build-manifest-v1",
                "version": 1,
                "kind": "build-manifest",
            },
            {
                "id": "weavec-diagnostics-v1",
                "version": 1,
                "kind": "diagnostics",
            },
            {
                "id": "weavec-compilation-trace-v1",
                "version": 1,
                "kind": "compilation-trace",
            },
            {
                "id": "weave-wir-core-v2",
                "version": 2,
                "kind": "intermediate-representation",
            },
        ],
        "commands": [
            {
                "name": "capabilities",
                "spelling": "capabilities --json",
                "audience": "public-tooling",
                "status": "stable",
                "protocols": ["weavec-capabilities-v1"],
            },
            {
                "name": "build",
                "spelling": "build",
                "audience": "public",
                "status": "stable",
                "protocols": [
                    "weavec-build-manifest-v1",
                    "weavec-diagnostics-v1",
                    "weavec-compilation-trace-v1",
                ],
            },
            {
                "name": "frontend",
                "spelling": "--frontend",
                "audience": "compiler-tooling",
                "status": "stable",
                "protocols": ["weave-wir-core-v2"],
            },
        ],
        "targets": {
            "default": "x86_64-unknown-linux-gnu",
            "installed": [
                {
                    "triple": "x86_64-unknown-linux-gnu",
                    "native": True,
                    "cross_compilation": False,
                    "runtime": "static-private-target-archive",
                    "optimization_levels": ["O0", "O3"],
                    "cpu_selection": ["native"],
                }
            ],
        },
        "features": [],
        "surface": {
            "grammar_document": "docs/language-reference.md",
            "canonical_document": "docs/canonical-surface.md",
            "child_count_excludes_head": True,
            "types": ["i32", "void"],
            "operators": [],
            "casts": [],
            "contextual_literals": [],
            "forms": [
                {
                    "head": "program",
                    "status": "canonical",
                    "arity": {"min_children": 0, "max_children": None},
                    "type_information": "none",
                    "feature": None,
                    "canonical_replacement": None,
                    "roles": [],
                }
            ],
            "compatibility_families": [],
        },
    }


def _install_wrapper(path: Path, *, frontend_fallback: bool) -> Path:
    delegate = path.with_name(path.name + ".delegate")
    os.replace(path, delegate)
    path.write_text(
        "#!/usr/bin/env python3\n"
        "from __future__ import annotations\n"
        "import json\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        f"REGISTRY = {_registry()!r}\n"
        f"DELEGATE = {str(delegate)!r}\n"
        f"FRONTEND_FALLBACK = {frontend_fallback!r}\n"
        "if sys.argv[1:] == ['capabilities', '--json']:\n"
        "    print(json.dumps(REGISTRY, sort_keys=True, separators=(',', ':')))\n"
        "    raise SystemExit(0)\n"
        "if FRONTEND_FALLBACK and len(sys.argv) >= 4 and sys.argv[1] == '--frontend':\n"
        "    Path(sys.argv[2]).write_text(\n"
        "        '(core-module (core-version 2) (decls))\\n',\n"
        "        encoding='utf-8',\n"
        "    )\n"
        "    raise SystemExit(0)\n"
        "os.execv(DELEGATE, [DELEGATE, *sys.argv[1:]])\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


@pytest.fixture(autouse=True)
def capability_aware_fake_compiler(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Give selected real-MCP fake compilers the final public handshake."""

    test_file = request.path.name
    frontend_fallback = _CAPABILITY_TEST_FILES.get(test_file)
    if frontend_fallback is None:
        return
    original = getattr(request.module, "_fake_compiler", None)
    if not callable(original):
        raise AssertionError(f"{test_file} does not expose _fake_compiler")

    def wrapped(path: Path, *args: Any, **kwargs: Any) -> Path:
        compiler = Path(original(path, *args, **kwargs))
        return _install_wrapper(compiler, frontend_fallback=frontend_fallback)

    monkeypatch.setattr(
        request.module,
        "_fake_compiler",
        wrapped,
    )
