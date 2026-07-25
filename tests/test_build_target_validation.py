from __future__ import annotations

from weave_frontend.build_targets import BuildTargetRegistry
from weave_frontend.target_validation import BuildTargetValidator


MAIN_SOURCE = """(program
  (name "main")
  (version "0.1")
  (entry main)
  (fn main
    (params)
    (returns i32)
    (do (return (call_i32 helper (const_i32 21))))))
"""

LIB_SOURCE = """(program
  (name "lib")
  (version "0.1")
  (fn helper
    (params (x i32))
    (returns i32)
    (do (return (mul_i32 (param_get x) (const_i32 2))))))
"""


class RecordingValidator:
    def __init__(self) -> None:
        self.calls: list[list[tuple[str, str]]] = []

    def validate_sources(self, sources: list[tuple[str, str]]):
        self.calls.append(list(sources))
        return {
            "available": True,
            "valid": True,
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "wir": "(core-module (core-version 1) (decls))\n",
        }


def test_target_validation_uses_pinned_revision_and_source_order(sexpr_workspace):
    sexpr_workspace.import_program(
        "sexpr-demo", "main", "main.weave", MAIN_SOURCE
    )
    sexpr_workspace.import_program(
        "sexpr-demo", "main", "lib.weave", LIB_SOURCE
    )

    registry = BuildTargetRegistry(sexpr_workspace)
    target = registry.set(
        "sexpr-demo",
        "main",
        "application",
        "main.weave",
        additional_documents=["lib.weave"],
    )
    target_revision = target["revision_id"]

    changed_library = LIB_SOURCE.replace("const_i32 2", "const_i32 3")
    sexpr_workspace.import_program(
        "sexpr-demo",
        "main",
        "lib.weave",
        changed_library,
        replace=True,
    )

    recording = RecordingValidator()
    sexpr_workspace.validator = recording
    result = BuildTargetValidator(registry).validate(
        "sexpr-demo",
        "application",
        revision_id=target_revision,
    )

    assert result["valid"] is True
    assert result["revision_id"] == target_revision
    assert result["documents"] == ["main.weave", "lib.weave"]
    assert result["build_target"]["name"] == "application"
    assert list(result["root_node_ids"]) == ["main.weave", "lib.weave"]

    validated_sources = recording.calls[0]
    assert [name for name, _ in validated_sources] == ["main.weave", "lib.weave"]
    assert "const_i32 2" in validated_sources[1][1]
    assert "const_i32 3" not in validated_sources[1][1]


def test_single_source_validator_api_remains_compatible():
    recording = RecordingValidator()

    result = recording.validate_sources([("program.weave", MAIN_SOURCE)])

    assert result["valid"] is True
    assert recording.calls == [[("program.weave", MAIN_SOURCE)]]
