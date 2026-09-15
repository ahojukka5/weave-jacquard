from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "agent_workflow_experiment.py"
SPEC = importlib.util.spec_from_file_location("agent_workflow_experiment", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def task(index: int, *, conflict: bool = False) -> dict[str, object]:
    return {
        "id": f"task-{index:02d}",
        "kind": "conflict" if conflict else "bugfix",
        "parallel": conflict,
        "base_revision": "a" * 40,
        "prompt": f"Repair task {index} without changing unrelated behavior.",
        "oracle": {"command": ["bash", f"test/task-{index:02d}.sh"]},
        "allowed_paths": ["src/", "test/"],
    }


def frozen_manifest() -> dict[str, object]:
    tasks = [task(index, conflict=index < 3) for index in range(16)]
    manifest: dict[str, object] = {
        "schema": MODULE.MANIFEST_SCHEMA,
        "status": "frozen",
        "source": {
            "repository": "ahojukka5/weavec",
            "revision": "b" * 40,
        },
        "model": {
            "provider": "test-provider",
            "model": "test-model",
            "configuration_id": "fixed-config-v1",
            "retry_budget": 1,
        },
        "arms": list(MODULE.ARMS),
        "tasks": tasks,
    }
    normalized = MODULE.validate_manifest(manifest)
    manifest["manifest_sha256"] = MODULE.canonical_manifest_hash(normalized)
    return manifest


def results_for(manifest: dict[str, object]) -> dict[str, object]:
    rows = []
    for task_entry in manifest["tasks"]:  # type: ignore[index]
        for arm in MODULE.ARMS:
            rows.append(
                {
                    "task_id": task_entry["id"],
                    "arm": arm,
                    "oracle_success": arm != "text",
                    "unrelated_regression": arm == "text",
                    "attempt_count": 1,
                    "repair_iterations": 0,
                    "invalid_intermediate_states": 1 if arm == "text" else 0,
                    "recovery_attempted": arm == "qualified",
                    "recovery_success": True if arm == "qualified" else None,
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "tool_operations": 3,
                    "wall_time_seconds": 1.5,
                    "retained_evidence_bytes": 1000 if arm == "qualified" else 0,
                }
            )
    return {
        "schema": MODULE.RESULT_SCHEMA,
        "manifest_sha256": manifest["manifest_sha256"],
        "rows": rows,
    }


def test_frozen_manifest_is_hash_bound(tmp_path: Path) -> None:
    manifest = frozen_manifest()
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    loaded = MODULE.load_manifest(path, require_frozen=True)

    assert loaded["corpus_summary"]["task_count"] == 16
    assert loaded["corpus_summary"]["parallel_task_count"] == 3
    assert loaded["manifest_sha256"] == manifest["manifest_sha256"]


def test_frozen_manifest_rejects_too_few_tasks() -> None:
    manifest = frozen_manifest()
    manifest["tasks"] = manifest["tasks"][:15]  # type: ignore[index]
    manifest.pop("manifest_sha256")

    with pytest.raises(MODULE.ProtocolError, match="at least 16 tasks"):
        MODULE.validate_manifest(manifest, require_frozen=True)


def test_results_require_every_task_arm_pair() -> None:
    manifest = MODULE.validate_manifest(frozen_manifest(), require_frozen=True)
    manifest["manifest_sha256"] = MODULE.canonical_manifest_hash(manifest)
    results = results_for(manifest)
    results["rows"].pop()  # type: ignore[union-attr]

    with pytest.raises(MODULE.ProtocolError, match="results are incomplete"):
        MODULE.validate_results(results, manifest)


def test_score_preserves_reliability_efficiency_separation() -> None:
    manifest = MODULE.validate_manifest(frozen_manifest(), require_frozen=True)
    manifest["manifest_sha256"] = MODULE.canonical_manifest_hash(manifest)
    validated = MODULE.validate_results(results_for(manifest), manifest)

    scored = MODULE.score(manifest, validated)

    assert scored["arms"]["text"]["success_rate"] == 0.0
    assert scored["arms"]["structure"]["success_rate"] == 1.0
    assert scored["arms"]["qualified"]["recovery_success_rate"] == 1.0
    assert scored["paired_success"]["text_to_structure"] == {
        "success_gains": 16,
        "success_losses": 0,
        "success_ties": 0,
    }
    assert scored["paired_success"]["structure_to_qualified"] == {
        "success_gains": 0,
        "success_losses": 0,
        "success_ties": 16,
    }
