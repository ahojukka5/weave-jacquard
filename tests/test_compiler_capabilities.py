from __future__ import annotations

import stat
from pathlib import Path

import pytest

from weave_frontend.compiler_capabilities import (
    CapabilityAwareWeavecValidator,
    CapabilityGrammarIndex,
    WeavecCapabilities,
)
from weave_frontend.compiler_limits import MAX_COMPILER_OUTPUT_BYTES, MAX_WIR_BYTES
from weave_frontend.errors import ValidationError


def _registry(
    *,
    version: str = "0.1.0",
    target: str = "x86_64-unknown-linux-gnu",
) -> dict[str, object]:
    protocols = [
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
    ]
    return {
        "format": "weavec-capabilities-v1",
        "schema_id": "urn:weavec:schema:capabilities:v1",
        "schema_version": 1,
        "compiler": {
            "name": "weavec",
            "version": version,
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
        "protocols": protocols,
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
            "default": target,
            "installed": [
                {
                    "triple": target,
                    "native": True,
                    "cross_compilation": False,
                    "runtime": "static-private-target-archive",
                    "optimization_levels": ["O0", "O3"],
                    "cpu_selection": ["native"],
                }
            ],
        },
        "features": [
            {"id": "typed-surface-elaboration", "status": "stable", "issue": 49}
        ],
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
                    "head": "fn",
                    "status": "canonical",
                    "arity": {"min_children": 4, "max_children": None},
                    "type_information": "explicit",
                    "feature": None,
                    "canonical_replacement": None,
                    "roles": [],
                },
                {
                    "head": "return_void",
                    "status": "canonical",
                    "arity": {"min_children": 0, "max_children": 0},
                    "type_information": "none",
                    "feature": None,
                    "canonical_replacement": None,
                    "roles": [],
                },
            ],
            "compatibility_families": [],
        },
    }


def _write_compiler(
    path: Path,
    registry: dict[str, object],
    *,
    calls: Path | None = None,
) -> None:
    call_path = str(calls) if calls is not None else ""
    path.write_text(
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        "import json\n"
        "import sys\n"
        f"REGISTRY = {registry!r}\n"
        f"CALLS = {call_path!r}\n"
        "if CALLS:\n"
        "    with Path(CALLS).open('a', encoding='utf-8') as stream:\n"
        "        stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "if sys.argv[1:] == ['capabilities', '--json']:\n"
        "    print(json.dumps(REGISTRY, sort_keys=True, separators=(',', ':')))\n"
        "elif sys.argv[1:] == ['--version']:\n"
        "    print('weavec test')\n"
        "elif len(sys.argv) >= 4 and sys.argv[1] == '--frontend':\n"
        "    Path(sys.argv[2]).write_text('(core-module (core-version 2) (decls))\\n')\n"
        "else:\n"
        "    raise SystemExit(2)\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_capability_registry_is_validated_and_cached_by_binary_hash(
    tmp_path: Path,
) -> None:
    compiler = tmp_path / "weavec"
    calls = tmp_path / "calls.jsonl"
    _write_compiler(compiler, _registry(), calls=calls)
    service = WeavecCapabilities(compiler, environment_fallback=False)

    first = service.load()
    second = service.load()

    assert first["_jacquard_identity"] == second["_jacquard_identity"]
    assert first["compiler"]["public_variant"] == "final"
    assert first["language"]["wir_core_version"] == 2
    recorded = calls.read_text(encoding="utf-8").splitlines()
    assert recorded == ['["capabilities", "--json"]']


def test_replacing_compiler_invalidates_cached_registry(tmp_path: Path) -> None:
    compiler = tmp_path / "weavec"
    calls = tmp_path / "calls.jsonl"
    service = WeavecCapabilities(compiler, environment_fallback=False)

    _write_compiler(compiler, _registry(version="0.1.0"), calls=calls)
    first = service.identity()
    _write_compiler(compiler, _registry(version="0.2.0"), calls=calls)
    second = service.identity()

    assert first["compiler_sha256"] != second["compiler_sha256"]
    assert first["compiler_version"] == "0.1.0"
    assert second["compiler_version"] == "0.2.0"
    assert len(calls.read_text(encoding="utf-8").splitlines()) == 2


def test_missing_required_protocol_fails_closed(tmp_path: Path) -> None:
    compiler = tmp_path / "weavec"
    registry = _registry()
    registry["protocols"] = [
        item
        for item in registry["protocols"]  # type: ignore[index]
        if item["id"] != "weavec-diagnostics-v1"
    ]
    _write_compiler(compiler, registry)

    with pytest.raises(ValidationError) as captured:
        WeavecCapabilities(compiler, environment_fallback=False).load()

    assert captured.value.code == "WEAVEC_PROTOCOL_UNSUPPORTED"


def test_requested_target_must_be_advertised(tmp_path: Path) -> None:
    compiler = tmp_path / "weavec"
    _write_compiler(compiler, _registry())
    service = WeavecCapabilities(compiler, environment_fallback=False)

    with pytest.raises(ValidationError) as captured:
        service.require(command="build", target="aarch64-unknown-linux-gnu")

    assert captured.value.code == "WEAVEC_TARGET_UNSUPPORTED"


def test_grammar_help_prefers_authoritative_registry_without_corpus(
    tmp_path: Path,
) -> None:
    compiler = tmp_path / "weavec"
    _write_compiler(compiler, _registry())
    capabilities = WeavecCapabilities(compiler, environment_fallback=False)
    grammar = CapabilityGrammarIndex(None, capabilities=capabilities)

    result = grammar.help(form="fn")

    assert result["found"] is True
    assert result["compiler_registry_available"] is True
    assert result["authoritative"]["authority"] == "weavec-capabilities-v1"
    assert result["authoritative"]["min_children"] == 4
    assert grammar.status()["authority"] == "weavec-capabilities-v1"


def test_frontend_validation_records_capability_identity(tmp_path: Path) -> None:
    compiler = tmp_path / "weavec"
    _write_compiler(compiler, _registry())
    capabilities = WeavecCapabilities(compiler, environment_fallback=False)
    validator = CapabilityAwareWeavecValidator(
        compiler,
        capabilities=capabilities,
        max_output_bytes=MAX_COMPILER_OUTPUT_BYTES,
        max_wir_bytes=MAX_WIR_BYTES,
        environment_fallback=False,
    )

    result = validator.validate("(program (name \"demo\") (version \"0.1\"))\n")

    assert result["available"] is True
    assert result["valid"] is True
    assert result["compiler_capabilities"]["format"] == "weavec-capabilities-v1"
    assert result["wir"] == "(core-module (core-version 2) (decls))\n"
