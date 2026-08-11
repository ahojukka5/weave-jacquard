from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from weave_frontend.builds import BuildTargetRegistry
from weave_frontend.errors import ValidationError
from weave_frontend.merges import (
    MAX_AFFECTED_TARGET_VALIDATIONS,
    MERGE_VALIDATION_SET_FORMAT,
    MergePreviewService,
    MergeTargetImpactService,
    MergeValidationService,
    MergeValidationSetService,
)


class _FakeValidator:
    def __init__(self, binary: Path, results: list[dict[str, Any]]) -> None:
        self.binary = binary
        self.results = results
        self.calls: list[list[tuple[str, str]]] = []

    def _active_binary(self) -> Path | None:
        return self.binary

    def validate_sources(self, sources: list[tuple[str, str]]) -> dict[str, Any]:
        self.calls.append(list(sources))
        index = min(len(self.calls) - 1, len(self.results) - 1)
        return dict(self.results[index])


class _UnavailableValidator:
    def __init__(self) -> None:
        self.calls: list[list[tuple[str, str]]] = []

    def _active_binary(self) -> Path | None:
        return None

    def validate_sources(self, sources: list[tuple[str, str]]) -> dict[str, Any]:
        self.calls.append(list(sources))
        return {
            "available": False,
            "valid": None,
            "returncode": None,
            "diagnostic": "compiler unavailable",
        }


def _compiler(tmp_path: Path) -> Path:
    binary = tmp_path / "fake-weavec"
    binary.write_bytes(b"merge validation set compiler\n")
    binary.chmod(0o755)
    return binary


def _valid_result() -> dict[str, Any]:
    return {
        "available": True,
        "valid": True,
        "returncode": 0,
        "stdout": "",
        "stderr": "",
        "wir": "(core-module (core-version 2))\n",
        "timed_out": False,
    }


def _invalid_result() -> dict[str, Any]:
    return {
        "available": True,
        "valid": False,
        "returncode": 10,
        "stdout": "",
        "stderr": "frontend rejected candidate",
        "wir": None,
        "timed_out": False,
    }


def _document(sexpr_workspace, name: str) -> dict[str, str]:
    created = sexpr_workspace.create_program(
        "sexpr-demo", "main", name, program_name=name
    )
    atom = sexpr_workspace.add_atom(
        "sexpr-demo",
        "main",
        name,
        created["node_id"],
        "string",
        name,
    )
    return {"root_id": created["node_id"], "atom_id": atom["node_id"]}


def _candidate(sexpr_workspace, *, uncovered: bool = False) -> dict[str, Any]:
    docs = {
        name: _document(sexpr_workspace, name)
        for name in ("main.weave", "lib.weave", "spare.weave", "orphan.weave")
    }
    targets = BuildTargetRegistry(sexpr_workspace)
    targets.set(
        "sexpr-demo",
        "main",
        "application",
        "main.weave",
        additional_documents=["lib.weave"],
    )
    targets.set("sexpr-demo", "main", "main-only", "main.weave")
    targets.set("sexpr-demo", "main", "removed", "lib.weave")
    targets.set("sexpr-demo", "main", "spare", "spare.weave")
    sexpr_workspace.create_branch("sexpr-demo", "target", from_branch="main")
    sexpr_workspace.create_branch("sexpr-demo", "source", from_branch="main")
    target_head = sexpr_workspace.set_atom(
        "sexpr-demo",
        "target",
        "spare.weave",
        docs["spare.weave"]["atom_id"],
        "target-spare",
    )["revision_id"]
    sexpr_workspace.set_atom(
        "sexpr-demo",
        "source",
        "main.weave",
        docs["main.weave"]["atom_id"],
        "source-main",
    )
    sexpr_workspace.set_atom(
        "sexpr-demo",
        "source",
        "lib.weave",
        docs["lib.weave"]["atom_id"],
        "source-lib",
    )
    if uncovered:
        sexpr_workspace.set_atom(
            "sexpr-demo",
            "source",
            "orphan.weave",
            docs["orphan.weave"]["atom_id"],
            "source-orphan",
        )
    source_head = targets.delete("sexpr-demo", "source", "removed")["revision_id"]
    return {
        "docs": docs,
        "target_head": target_head,
        "source_head": source_head,
    }


def _service(sexpr_workspace) -> MergeValidationSetService:
    targets = BuildTargetRegistry(sexpr_workspace)
    previews = MergePreviewService(sexpr_workspace)
    impacts = MergeTargetImpactService(previews, targets)
    validations = MergeValidationService(sexpr_workspace, previews, targets)
    return MergeValidationSetService(impacts, validations)


def test_validation_set_checks_all_affected_surviving_targets_in_order(
    sexpr_workspace,
    tmp_path: Path,
) -> None:
    values = _candidate(sexpr_workspace)
    fake = _FakeValidator(_compiler(tmp_path), [_valid_result()])
    sexpr_workspace.validator = fake
    service = _service(sexpr_workspace)

    first = service.validate("sexpr-demo", "target", "source")
    second = service.validate("sexpr-demo", "target", "source")

    assert first == second
    assert first["format"] == MERGE_VALIDATION_SET_FORMAT
    assert first["ready_for_publication"] is True
    assert first["coverage_passed"] is True
    assert first["affected_target_count"] == 3
    assert first["affected_surviving_targets"] == ["application", "main-only"]
    assert first["skipped_removed_targets"] == ["removed"]
    assert first["validated_target_count"] == 2
    assert first["passed_targets"] == ["application", "main-only"]
    assert first["failed_targets"] == []
    assert first["unavailable_targets"] == []
    assert [item["target"] for item in first["target_validations"]] == [
        "application",
        "main-only",
    ]
    assert [document for document, _ in fake.calls[0]] == [
        "main.weave",
        "lib.weave",
    ]
    assert [document for document, _ in fake.calls[1]] == ["main.weave"]
    assert sexpr_workspace.branch_head("sexpr-demo", "target") == values["target_head"]
    assert sexpr_workspace.branch_head("sexpr-demo", "source") == values["source_head"]
    service.require_ready(first)


def test_validation_set_aggregates_invalid_targets(
    sexpr_workspace,
    tmp_path: Path,
) -> None:
    _candidate(sexpr_workspace)
    sexpr_workspace.validator = _FakeValidator(
        _compiler(tmp_path),
        [_valid_result(), _invalid_result()],
    )
    service = _service(sexpr_workspace)

    result = service.validate("sexpr-demo", "target", "source")

    assert result["ready_for_publication"] is False
    assert result["passed_targets"] == ["application"]
    assert result["failed_targets"] == ["main-only"]
    assert result["validated_target_count"] == 2
    with pytest.raises(ValidationError) as raised:
        service.require_ready(result)
    assert raised.value.code == "MERGE_VALIDATION_FAILED"
    assert "main-only" in str(raised.value)


def test_uncovered_documents_block_before_compiler_by_default(
    sexpr_workspace,
    tmp_path: Path,
) -> None:
    _candidate(sexpr_workspace, uncovered=True)
    fake = _FakeValidator(_compiler(tmp_path), [_valid_result()])
    sexpr_workspace.validator = fake
    service = _service(sexpr_workspace)

    result = service.validate("sexpr-demo", "target", "source")

    assert result["coverage_passed"] is False
    assert result["uncovered_changed_documents"] == ["orphan.weave"]
    assert result["validated_target_count"] == 0
    assert result["ready_for_publication"] is False
    assert fake.calls == []
    with pytest.raises(ValidationError) as raised:
        service.require_ready(result)
    assert raised.value.code == "MERGE_UNCOVERED_DOCUMENTS"


def test_uncovered_documents_can_be_explicitly_allowed(
    sexpr_workspace,
    tmp_path: Path,
) -> None:
    _candidate(sexpr_workspace, uncovered=True)
    fake = _FakeValidator(_compiler(tmp_path), [_valid_result()])
    sexpr_workspace.validator = fake
    service = _service(sexpr_workspace)

    result = service.validate(
        "sexpr-demo",
        "target",
        "source",
        allow_uncovered_documents=True,
    )

    assert result["coverage_passed"] is True
    assert result["allow_uncovered_documents"] is True
    assert result["uncovered_changed_documents"] == ["orphan.weave"]
    assert result["validated_target_count"] == 2
    assert result["ready_for_publication"] is True
    assert len(fake.calls) == 2
    service.require_ready(result)


def test_unavailable_compiler_is_aggregated_for_every_target(
    sexpr_workspace,
) -> None:
    _candidate(sexpr_workspace)
    fake = _UnavailableValidator()
    sexpr_workspace.validator = fake
    service = _service(sexpr_workspace)

    result = service.validate("sexpr-demo", "target", "source")

    assert result["ready_for_publication"] is False
    assert result["unavailable_targets"] == ["application", "main-only"]
    assert result["unavailable_target_count"] == 2
    assert len(fake.calls) == 2
    with pytest.raises(ValidationError) as raised:
        service.require_ready(result)
    assert raised.value.code == "MERGE_VALIDATION_UNAVAILABLE"


def test_validation_set_rejects_stale_preview(
    sexpr_workspace,
    tmp_path: Path,
) -> None:
    values = _candidate(sexpr_workspace)
    preview = MergePreviewService(sexpr_workspace).preview(
        "sexpr-demo", "target", "source"
    )
    sexpr_workspace.set_atom(
        "sexpr-demo",
        "source",
        "orphan.weave",
        values["docs"]["orphan.weave"]["atom_id"],
        "advanced",
    )
    sexpr_workspace.validator = _FakeValidator(
        _compiler(tmp_path), [_valid_result()]
    )

    with pytest.raises(ValidationError) as raised:
        _service(sexpr_workspace).validate(
            "sexpr-demo",
            "target",
            "source",
            preview_id=preview["preview_id"],
        )
    assert raised.value.code == "STALE_MERGE_PREVIEW"


def test_validation_set_bounds_compiler_fanout(
    sexpr_workspace,
    tmp_path: Path,
) -> None:
    doc = _document(sexpr_workspace, "main.weave")
    targets = BuildTargetRegistry(sexpr_workspace)
    for index in range(MAX_AFFECTED_TARGET_VALIDATIONS + 1):
        targets.set(
            "sexpr-demo",
            "main",
            f"target-{index:03d}",
            "main.weave",
        )
    sexpr_workspace.create_branch("sexpr-demo", "target", from_branch="main")
    sexpr_workspace.create_branch("sexpr-demo", "source", from_branch="main")
    sexpr_workspace.set_atom(
        "sexpr-demo",
        "source",
        "main.weave",
        doc["atom_id"],
        "changed",
    )
    fake = _FakeValidator(_compiler(tmp_path), [_valid_result()])
    sexpr_workspace.validator = fake

    with pytest.raises(ValidationError) as raised:
        _service(sexpr_workspace).validate(
            "sexpr-demo", "target", "source"
        )
    assert raised.value.code == "TOO_MANY_AFFECTED_TARGETS"
    assert fake.calls == []


def test_validation_set_requires_boolean_uncovered_policy(
    sexpr_workspace,
    tmp_path: Path,
) -> None:
    _candidate(sexpr_workspace)
    sexpr_workspace.validator = _FakeValidator(
        _compiler(tmp_path), [_valid_result()]
    )

    with pytest.raises(ValidationError) as raised:
        _service(sexpr_workspace).validate(
            "sexpr-demo",
            "target",
            "source",
            allow_uncovered_documents="yes",  # type: ignore[arg-type]
        )
    assert raised.value.code == "INVALID_UNCOVERED_DOCUMENT_POLICY"
