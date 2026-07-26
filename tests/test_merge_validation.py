from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from weave_frontend.build_targets import BuildTargetRegistry
from weave_frontend.errors import ConflictError, ValidationError
from weave_frontend.merge_preview import MergePreviewService
from weave_frontend.merge_validation import (
    MAX_VALIDATION_OUTPUT_CHARACTERS,
    MERGE_VALIDATION_FORMAT,
    MergeValidationService,
)


class _FakeValidator:
    def __init__(self, binary: Path, result: dict[str, Any]) -> None:
        self.binary = binary
        self.result = result
        self.calls: list[list[tuple[str, str]]] = []

    def _active_binary(self) -> Path | None:
        return self.binary

    def validate_sources(self, sources: list[tuple[str, str]]) -> dict[str, Any]:
        self.calls.append(list(sources))
        return dict(self.result)


class _UnavailableValidator:
    def _active_binary(self) -> Path | None:
        return None

    def validate_sources(self, sources: list[tuple[str, str]]) -> dict[str, Any]:
        return {
            "available": False,
            "valid": None,
            "returncode": None,
            "diagnostic": "compiler unavailable",
            "documents": [document for document, _ in sources],
        }


def _service(sexpr_workspace) -> MergeValidationService:
    targets = BuildTargetRegistry(sexpr_workspace)
    return MergeValidationService(
        sexpr_workspace,
        MergePreviewService(sexpr_workspace),
        targets,
    )


def _clean_candidate(sexpr_workspace) -> dict[str, Any]:
    created = sexpr_workspace.create_program(
        "sexpr-demo",
        "main",
        "main.weave",
        program_name="merge-validation",
    )
    targets = BuildTargetRegistry(sexpr_workspace)
    target = targets.set(
        "sexpr-demo",
        "main",
        "application",
        "main.weave",
    )
    sexpr_workspace.create_branch("sexpr-demo", "target", from_branch="main")
    sexpr_workspace.create_branch("sexpr-demo", "source", from_branch="main")
    target_edit = sexpr_workspace.create_form(
        "sexpr-demo",
        "target",
        "main.weave",
        created["node_id"],
        "target_only",
    )
    source_edit = sexpr_workspace.create_form(
        "sexpr-demo",
        "source",
        "main.weave",
        created["node_id"],
        "source_only",
    )
    return {
        "root_id": created["node_id"],
        "target_definition_revision": target["revision_id"],
        "target_head": target_edit["revision_id"],
        "source_head": source_edit["revision_id"],
    }


def _compiler(tmp_path: Path) -> Path:
    binary = tmp_path / "fake-weavec"
    binary.write_bytes(b"fake compiler for deterministic identity\n")
    binary.chmod(0o755)
    return binary


def test_candidate_validation_is_deterministic_and_non_mutating(
    sexpr_workspace,
    tmp_path: Path,
) -> None:
    values = _clean_candidate(sexpr_workspace)
    binary = _compiler(tmp_path)
    fake = _FakeValidator(
        binary,
        {
            "available": True,
            "valid": True,
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "wir": "(core-module (core-version 2))\n",
            "timed_out": False,
        },
    )
    sexpr_workspace.validator = fake
    service = _service(sexpr_workspace)
    preview = service.previews.preview("sexpr-demo", "target", "source")

    first = service.validate(
        "sexpr-demo",
        "target",
        "source",
        "application",
        preview_id=preview["preview_id"],
    )
    second = service.validate(
        "sexpr-demo",
        "target",
        "source",
        "application",
        preview_id=preview["preview_id"],
    )

    assert first == second
    assert first["format"] == MERGE_VALIDATION_FORMAT
    assert first["preview_id"] == preview["preview_id"]
    assert first["valid"] is True
    assert first["available"] is True
    assert first["documents"] == ["main.weave"]
    assert first["build_target"] == {
        "name": "application",
        "document": "main.weave",
        "additional_documents": [],
        "compiler_target": "native",
    }
    assert first["compiler"]["sha256"] == hashlib.sha256(binary.read_bytes()).hexdigest()
    assert first["wir_bytes"] > 0
    assert first["wir_sha256"]
    assert first["sources"][0]["source_bytes"] > 0
    assert "(target_only)" in fake.calls[0][0][1]
    assert "(source_only)" in fake.calls[0][0][1]
    assert sexpr_workspace.branch_head("sexpr-demo", "target") == values["target_head"]
    assert sexpr_workspace.branch_head("sexpr-demo", "source") == values["source_head"]
    service.require_valid(first)


def test_validation_id_changes_with_compiler_identity(
    sexpr_workspace,
    tmp_path: Path,
) -> None:
    _clean_candidate(sexpr_workspace)
    first_binary = _compiler(tmp_path)
    first = _FakeValidator(
        first_binary,
        {"available": True, "valid": True, "returncode": 0, "wir": "ok"},
    )
    sexpr_workspace.validator = first
    service = _service(sexpr_workspace)
    initial = service.validate("sexpr-demo", "target", "source", "application")

    second_binary = tmp_path / "fake-weavec-2"
    second_binary.write_bytes(b"different compiler\n")
    second_binary.chmod(0o755)
    sexpr_workspace.validator = _FakeValidator(
        second_binary,
        {"available": True, "valid": True, "returncode": 0, "wir": "ok"},
    )
    changed = service.validate("sexpr-demo", "target", "source", "application")

    assert changed["preview_id"] == initial["preview_id"]
    assert changed["validation_id"] != initial["validation_id"]
    assert changed["compiler"]["sha256"] != initial["compiler"]["sha256"]


def test_candidate_validation_rejects_stale_preview(
    sexpr_workspace,
    tmp_path: Path,
) -> None:
    values = _clean_candidate(sexpr_workspace)
    preview = MergePreviewService(sexpr_workspace).preview(
        "sexpr-demo", "target", "source"
    )
    sexpr_workspace.create_form(
        "sexpr-demo",
        "source",
        "main.weave",
        values["root_id"],
        "advanced",
    )
    sexpr_workspace.validator = _FakeValidator(
        _compiler(tmp_path),
        {"available": True, "valid": True, "returncode": 0},
    )

    with pytest.raises(ValidationError) as raised:
        _service(sexpr_workspace).validate(
            "sexpr-demo",
            "target",
            "source",
            "application",
            preview_id=preview["preview_id"],
        )

    assert raised.value.code == "STALE_MERGE_PREVIEW"


def test_candidate_validation_reports_conflict_before_compiler(
    sexpr_workspace,
    tmp_path: Path,
) -> None:
    created = sexpr_workspace.create_program(
        "sexpr-demo", "main", "main.weave", program_name="conflict"
    )
    atom = sexpr_workspace.add_atom(
        "sexpr-demo",
        "main",
        "main.weave",
        created["node_id"],
        "string",
        "base",
    )
    BuildTargetRegistry(sexpr_workspace).set(
        "sexpr-demo", "main", "application", "main.weave"
    )
    sexpr_workspace.create_branch("sexpr-demo", "target", from_branch="main")
    sexpr_workspace.create_branch("sexpr-demo", "source", from_branch="main")
    sexpr_workspace.set_atom(
        "sexpr-demo", "target", "main.weave", atom["node_id"], "target"
    )
    sexpr_workspace.set_atom(
        "sexpr-demo", "source", "main.weave", atom["node_id"], "source"
    )
    fake = _FakeValidator(
        _compiler(tmp_path),
        {"available": True, "valid": True, "returncode": 0},
    )
    sexpr_workspace.validator = fake

    with pytest.raises(ConflictError):
        _service(sexpr_workspace).validate(
            "sexpr-demo", "target", "source", "application"
        )

    assert fake.calls == []


def test_validation_output_is_bounded(sexpr_workspace, tmp_path: Path) -> None:
    _clean_candidate(sexpr_workspace)
    large = "x" * (MAX_VALIDATION_OUTPUT_CHARACTERS + 100)
    sexpr_workspace.validator = _FakeValidator(
        _compiler(tmp_path),
        {
            "available": True,
            "valid": False,
            "returncode": 10,
            "stdout": large,
            "stderr": large,
            "wir": None,
        },
    )

    result = _service(sexpr_workspace).validate(
        "sexpr-demo", "target", "source", "application"
    )

    assert len(result["stdout"]) == MAX_VALIDATION_OUTPUT_CHARACTERS
    assert len(result["stderr"]) == MAX_VALIDATION_OUTPUT_CHARACTERS
    assert result["stdout_truncated"] is True
    assert result["stderr_truncated"] is True
    assert result["wir_bytes"] == 0
    with pytest.raises(ValidationError) as raised:
        MergeValidationService.require_valid(result)
    assert raised.value.code == "MERGE_VALIDATION_FAILED"


def test_unavailable_compiler_blocks_validated_publication(sexpr_workspace) -> None:
    _clean_candidate(sexpr_workspace)
    sexpr_workspace.validator = _UnavailableValidator()
    result = _service(sexpr_workspace).validate(
        "sexpr-demo", "target", "source", "application"
    )

    assert result["available"] is False
    assert result["valid"] is None
    assert result["compiler"] == {"available": False, "path": None, "sha256": None}
    with pytest.raises(ValidationError) as raised:
        MergeValidationService.require_valid(result)
    assert raised.value.code == "MERGE_VALIDATION_UNAVAILABLE"
