#!/usr/bin/env python3
"""Validate and score the frozen agent-workflow comparison protocol.

This module is intentionally standard-library-only. It defines the evidence
shape for research issue #274 without adding product behavior to Jacquard.
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA = "weave-agent-workflow-manifest-v1"
RESULT_SCHEMA = "weave-agent-workflow-results-v1"
SCORE_SCHEMA = "weave-agent-workflow-score-v1"
ARMS = ("text", "structure", "qualified")
TASK_KINDS = {"bugfix", "feature", "refactor", "conflict"}


class ProtocolError(ValueError):
    pass


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"cannot load JSON from {path}: {exc}") from exc


def _require_dict(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError(f"{context} must be an object")
    return value


def _require_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProtocolError(f"{context} must be a non-empty string")
    return value


def _require_nonnegative_int(value: Any, context: str, *, allow_none: bool = False) -> int | None:
    if allow_none and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProtocolError(f"{context} must be a non-negative integer")
    return value


def _require_nonnegative_number(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ProtocolError(f"{context} must be a non-negative number")
    return float(value)


def _validate_command(value: Any, context: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ProtocolError(f"{context} must be a non-empty argument list")
    command: list[str] = []
    for index, item in enumerate(value):
        command.append(_require_string(item, f"{context}[{index}]"))
    return command


def validate_manifest(value: Any, *, require_frozen: bool = False) -> dict[str, Any]:
    manifest = _require_dict(value, "manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ProtocolError(f"manifest schema must be {MANIFEST_SCHEMA}")

    status = manifest.get("status")
    if status not in {"draft", "frozen"}:
        raise ProtocolError("manifest status must be draft or frozen")
    if require_frozen and status != "frozen":
        raise ProtocolError("experiment execution requires a frozen manifest")

    source = _require_dict(manifest.get("source"), "manifest.source")
    _require_string(source.get("repository"), "manifest.source.repository")
    revision = _require_string(source.get("revision"), "manifest.source.revision")
    if status == "frozen" and len(revision) < 12:
        raise ProtocolError("frozen source revision must be an immutable commit identifier")

    model = _require_dict(manifest.get("model"), "manifest.model")
    for field in ("provider", "model", "configuration_id"):
        _require_string(model.get(field), f"manifest.model.{field}")
    _require_nonnegative_int(model.get("retry_budget"), "manifest.model.retry_budget")

    arms = manifest.get("arms")
    if arms != list(ARMS):
        raise ProtocolError(f"manifest arms must be exactly {list(ARMS)}")

    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ProtocolError("manifest.tasks must be a non-empty list")
    ids: set[str] = set()
    kinds = Counter()
    conflict_count = 0
    normalized_tasks: list[dict[str, Any]] = []
    for index, raw_task in enumerate(tasks):
        task = _require_dict(raw_task, f"manifest.tasks[{index}]")
        task_id = _require_string(task.get("id"), f"manifest.tasks[{index}].id")
        if task_id in ids:
            raise ProtocolError(f"duplicate task id: {task_id}")
        ids.add(task_id)
        kind = task.get("kind")
        if kind not in TASK_KINDS:
            raise ProtocolError(f"task {task_id}: kind must be one of {sorted(TASK_KINDS)}")
        kinds[kind] += 1
        is_parallel = task.get("parallel")
        if not isinstance(is_parallel, bool):
            raise ProtocolError(f"task {task_id}: parallel must be boolean")
        if is_parallel:
            conflict_count += 1
        if kind == "conflict" and not is_parallel:
            raise ProtocolError(f"task {task_id}: conflict tasks must set parallel=true")
        base_revision = _require_string(task.get("base_revision"), f"task {task_id}.base_revision")
        if status == "frozen" and len(base_revision) < 12:
            raise ProtocolError(f"task {task_id}: frozen base_revision must be immutable")
        _require_string(task.get("prompt"), f"task {task_id}.prompt")
        oracle = _require_dict(task.get("oracle"), f"task {task_id}.oracle")
        _validate_command(oracle.get("command"), f"task {task_id}.oracle.command")
        allowed_paths = task.get("allowed_paths")
        if not isinstance(allowed_paths, list) or not allowed_paths:
            raise ProtocolError(f"task {task_id}: allowed_paths must be a non-empty list")
        for path_index, path in enumerate(allowed_paths):
            _require_string(path, f"task {task_id}.allowed_paths[{path_index}]")
        normalized_tasks.append(task)

    if status == "frozen" and len(tasks) < 16:
        raise ProtocolError("frozen first corpus must contain at least 16 tasks")
    if status == "frozen" and conflict_count < 3:
        raise ProtocolError("frozen first corpus must contain at least 3 parallel/conflict tasks")

    return {
        **manifest,
        "tasks": normalized_tasks,
        "corpus_summary": {
            "task_count": len(tasks),
            "parallel_task_count": conflict_count,
            "kind_counts": dict(sorted(kinds.items())),
        },
    }


def validate_results(value: Any, manifest: dict[str, Any]) -> dict[str, Any]:
    result = _require_dict(value, "results")
    if result.get("schema") != RESULT_SCHEMA:
        raise ProtocolError(f"results schema must be {RESULT_SCHEMA}")
    if result.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise ProtocolError("results manifest_sha256 does not match manifest")

    rows = result.get("rows")
    if not isinstance(rows, list):
        raise ProtocolError("results.rows must be a list")
    task_ids = {task["id"] for task in manifest["tasks"]}
    expected = {(task_id, arm) for task_id in task_ids for arm in ARMS}
    seen: set[tuple[str, str]] = set()
    normalized_rows: list[dict[str, Any]] = []

    for index, raw_row in enumerate(rows):
        row = _require_dict(raw_row, f"results.rows[{index}]")
        task_id = _require_string(row.get("task_id"), f"results.rows[{index}].task_id")
        arm = _require_string(row.get("arm"), f"results.rows[{index}].arm")
        key = (task_id, arm)
        if key not in expected:
            raise ProtocolError(f"unexpected task/arm row: {task_id}/{arm}")
        if key in seen:
            raise ProtocolError(f"duplicate task/arm row: {task_id}/{arm}")
        seen.add(key)

        for field in ("oracle_success", "unrelated_regression"):
            if not isinstance(row.get(field), bool):
                raise ProtocolError(f"{task_id}/{arm}: {field} must be boolean")
        recovery_attempted = row.get("recovery_attempted")
        if not isinstance(recovery_attempted, bool):
            raise ProtocolError(f"{task_id}/{arm}: recovery_attempted must be boolean")
        recovery_success = row.get("recovery_success")
        if recovery_success is not None and not isinstance(recovery_success, bool):
            raise ProtocolError(f"{task_id}/{arm}: recovery_success must be boolean or null")
        if not recovery_attempted and recovery_success is not None:
            raise ProtocolError(f"{task_id}/{arm}: recovery_success must be null when not attempted")

        for field in (
            "attempt_count",
            "repair_iterations",
            "invalid_intermediate_states",
            "tool_operations",
            "retained_evidence_bytes",
        ):
            _require_nonnegative_int(row.get(field), f"{task_id}/{arm}.{field}")
        if row["attempt_count"] < 1:
            raise ProtocolError(f"{task_id}/{arm}: attempt_count must be at least 1")
        if row["attempt_count"] > manifest["model"]["retry_budget"] + 1:
            raise ProtocolError(f"{task_id}/{arm}: attempt_count exceeds frozen retry budget")
        for field in ("input_tokens", "output_tokens"):
            _require_nonnegative_int(row.get(field), f"{task_id}/{arm}.{field}", allow_none=True)
        _require_nonnegative_number(row.get("wall_time_seconds"), f"{task_id}/{arm}.wall_time_seconds")
        normalized_rows.append(row)

    missing = expected - seen
    if missing:
        preview = ", ".join(f"{task}/{arm}" for task, arm in sorted(missing)[:8])
        raise ProtocolError(f"results are incomplete; missing {len(missing)} task/arm rows: {preview}")
    return {**result, "rows": normalized_rows}


def _median(values: list[float]) -> float | None:
    return None if not values else float(statistics.median(values))


def score(manifest: dict[str, Any], results: dict[str, Any]) -> dict[str, Any]:
    by_arm: dict[str, list[dict[str, Any]]] = {arm: [] for arm in ARMS}
    for row in results["rows"]:
        by_arm[row["arm"]].append(row)

    arm_scores: dict[str, dict[str, Any]] = {}
    for arm in ARMS:
        rows = by_arm[arm]
        recovery_rows = [row for row in rows if row["recovery_attempted"]]
        token_rows = [row for row in rows if row["input_tokens"] is not None and row["output_tokens"] is not None]
        arm_scores[arm] = {
            "task_count": len(rows),
            "success_count": sum(row["oracle_success"] for row in rows),
            "success_rate": sum(row["oracle_success"] for row in rows) / len(rows),
            "unrelated_regression_count": sum(row["unrelated_regression"] for row in rows),
            "unrelated_regression_rate": sum(row["unrelated_regression"] for row in rows) / len(rows),
            "median_repair_iterations": _median([float(row["repair_iterations"]) for row in rows]),
            "median_invalid_intermediate_states": _median(
                [float(row["invalid_intermediate_states"]) for row in rows]
            ),
            "recovery_attempt_count": len(recovery_rows),
            "recovery_success_count": sum(row["recovery_success"] is True for row in recovery_rows),
            "recovery_success_rate": (
                None
                if not recovery_rows
                else sum(row["recovery_success"] is True for row in recovery_rows) / len(recovery_rows)
            ),
            "median_tool_operations": _median([float(row["tool_operations"]) for row in rows]),
            "median_wall_time_seconds": _median([float(row["wall_time_seconds"]) for row in rows]),
            "token_complete_task_count": len(token_rows),
            "median_total_tokens": _median(
                [float(row["input_tokens"] + row["output_tokens"]) for row in token_rows]
            ),
            "median_retained_evidence_bytes": _median(
                [float(row["retained_evidence_bytes"]) for row in rows]
            ),
        }

    paired = {}
    for left, right in (("text", "structure"), ("structure", "qualified")):
        left_rows = {row["task_id"]: row for row in by_arm[left]}
        right_rows = {row["task_id"]: row for row in by_arm[right]}
        wins = losses = ties = 0
        for task_id in sorted(left_rows):
            a = left_rows[task_id]["oracle_success"]
            b = right_rows[task_id]["oracle_success"]
            if a == b:
                ties += 1
            elif b:
                wins += 1
            else:
                losses += 1
        paired[f"{left}_to_{right}"] = {
            "success_gains": wins,
            "success_losses": losses,
            "success_ties": ties,
        }

    return {
        "schema": SCORE_SCHEMA,
        "manifest_sha256": manifest["manifest_sha256"],
        "task_count": len(manifest["tasks"]),
        "arms": arm_scores,
        "paired_success": paired,
        "interpretation": (
            "Descriptive evidence only. Reliability and efficiency metrics are deliberately "
            "reported separately; scientific interpretation belongs in the parent research study."
        ),
    }


def canonical_manifest_hash(manifest: dict[str, Any]) -> str:
    import hashlib

    payload = dict(manifest)
    payload.pop("manifest_sha256", None)
    payload.pop("corpus_summary", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_manifest(path: Path, *, require_frozen: bool = False) -> dict[str, Any]:
    manifest = validate_manifest(_load_json(path), require_frozen=require_frozen)
    expected = canonical_manifest_hash(manifest)
    declared = manifest.get("manifest_sha256")
    if manifest["status"] == "frozen":
        if declared != expected:
            raise ProtocolError(f"frozen manifest_sha256 mismatch: expected {expected}")
    elif declared is not None and declared != expected:
        raise ProtocolError(f"draft manifest_sha256 mismatch: expected {expected}")
    manifest["manifest_sha256"] = expected
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate-manifest")
    validate_parser.add_argument("manifest", type=Path)
    validate_parser.add_argument("--require-frozen", action="store_true")

    hash_parser = subparsers.add_parser("hash-manifest")
    hash_parser.add_argument("manifest", type=Path)

    score_parser = subparsers.add_parser("score")
    score_parser.add_argument("manifest", type=Path)
    score_parser.add_argument("results", type=Path)
    score_parser.add_argument("--output", type=Path)

    args = parser.parse_args()
    try:
        if args.command == "validate-manifest":
            manifest = load_manifest(args.manifest, require_frozen=args.require_frozen)
            print(json.dumps(manifest["corpus_summary"], indent=2, sort_keys=True))
            return 0
        if args.command == "hash-manifest":
            manifest = validate_manifest(_load_json(args.manifest))
            print(canonical_manifest_hash(manifest))
            return 0
        if args.command == "score":
            manifest = load_manifest(args.manifest, require_frozen=True)
            results = validate_results(_load_json(args.results), manifest)
            scored = score(manifest, results)
            encoded = json.dumps(scored, indent=2, sort_keys=True) + "\n"
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(encoded, encoding="utf-8")
            else:
                print(encoded, end="")
            return 0
    except ProtocolError as exc:
        parser.error(str(exc))
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
