from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from weave_frontend.build_targets import BuildTargetRegistry
from weave_frontend.errors import ValidationError
from weave_frontend.merge_impact import MergeTargetImpactService
from weave_frontend.merge_preview import MergePreviewService
from weave_frontend.merge_validation import MergeValidationService
from weave_frontend.merge_validation_set import MergeValidationSetService


class _FakeValidator:
    def __init__(self, binary: Path) -> None:
        self.binary = binary
        self.calls: list[list[tuple[str, str]]] = []

    def _active_binary(self) -> Path | None:
        return self.binary

    def validate_sources(self, sources: list[tuple[str, str]]) -> dict[str, Any]:
        self.calls.append(list(sources))
        return {
            "available": True,
            "valid": True,
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "wir": "(core-module (core-version 2))\n",
            "timed_out": False,
        }


def _service(sexpr_workspace) -> MergeValidationSetService:
    targets = BuildTargetRegistry(sexpr_workspace)
    previews = MergePreviewService(sexpr_workspace)
    return MergeValidationSetService(
        MergeTargetImpactService(previews, targets),
        MergeValidationService(sexpr_workspace, previews, targets),
    )


def _two_target_candidate(sexpr_workspace) -> None:
    created = sexpr_workspace.create_program(
        "sexpr-demo",
        "main",
        "main.weave",
        program_name="limits",
    )
    atom = sexpr_workspace.add_atom(
        "sexpr-demo",
        "main",
        "main.weave",
        created["node_id"],
        "string",
        "before",
    )
    targets = BuildTargetRegistry(sexpr_workspace)
    targets.set("sexpr-demo", "main", "application", "main.weave")
    targets.set("sexpr-demo", "main", "mirror", "main.weave")
    sexpr_workspace.create_branch("sexpr-demo", "target", from_branch="main")
    sexpr_workspace.create_branch("sexpr-demo", "source", from_branch="main")
    sexpr_workspace.set_atom(
        "sexpr-demo",
        "source",
        "main.weave",
        atom["node_id"],
        "after",
    )


def _compiler(tmp_path: Path) -> Path:
    binary = tmp_path / "fake-weavec"
    binary.write_bytes(b"merge validation limit compiler\n")
    binary.chmod(0o755)
    return binary


def test_policy_limit_rejects_before_any_compiler_call(
    sexpr_workspace,
    tmp_path: Path,
) -> None:
    _two_target_candidate(sexpr_workspace)
    fake = _FakeValidator(_compiler(tmp_path))
    sexpr_workspace.validator = fake

    with pytest.raises(ValidationError) as raised:
        _service(sexpr_workspace).validate(
            "sexpr-demo",
            "target",
            "source",
            max_target_validations=1,
        )

    assert raised.value.code == "TOO_MANY_AFFECTED_TARGETS"
    assert "maximum is 1" in str(raised.value)
    assert fake.calls == []


def test_effective_limit_is_bound_into_validation_set_identity(
    sexpr_workspace,
    tmp_path: Path,
) -> None:
    _two_target_candidate(sexpr_workspace)
    fake = _FakeValidator(_compiler(tmp_path))
    sexpr_workspace.validator = fake
    service = _service(sexpr_workspace)

    strict = service.validate(
        "sexpr-demo",
        "target",
        "source",
        max_target_validations=2,
    )
    relaxed = service.validate(
        "sexpr-demo",
        "target",
        "source",
        max_target_validations=3,
    )

    assert strict["ready_for_publication"] is True
    assert relaxed["ready_for_publication"] is True
    assert strict["max_target_validations"] == 2
    assert relaxed["max_target_validations"] == 3
    assert strict["validation_set_id"] != relaxed["validation_set_id"]
    assert len(fake.calls) == 4


@pytest.mark.parametrize("value", [0, 65, True, "4"])
def test_validation_set_rejects_invalid_effective_limits(
    sexpr_workspace,
    value,
) -> None:
    with pytest.raises(ValidationError) as raised:
        _service(sexpr_workspace).validate(
            "sexpr-demo",
            "target",
            "source",
            max_target_validations=value,
        )

    assert raised.value.code == "INVALID_AFFECTED_TARGET_LIMIT"
