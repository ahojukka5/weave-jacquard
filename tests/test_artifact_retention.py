from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

from weave_frontend.artifact_reachability import ArtifactReconciliationService
from weave_frontend.artifact_reconciliation import (
    RetainedArtifactFamily,
    RetainedArtifactInventoryService,
)
from weave_frontend.artifact_retention import (
    ARTIFACT_RETENTION_PLAN_FORMAT,
    ARTIFACT_RETENTION_POLICY_FORMAT,
    ArtifactRetentionPlanner,
)
from weave_frontend.database import Database
from weave_frontend.errors import ValidationError

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_SECOND = 1_000_000_000


def _fixture(
    tmp_path: Path,
) -> tuple[
    Database,
    Path,
    dict[str, dict[str, Any]],
    ArtifactReconciliationService,
    str,
]:
    database = Database(tmp_path / "jacquard.db")
    _project_id, revision_id = database.initialize_project("demo")
    root = tmp_path / "builds"
    root.mkdir()
    evidence: dict[str, dict[str, Any]] = {}

    def verify(artifact_id: str) -> dict[str, Any]:
        return evidence[artifact_id]

    inventory = RetainedArtifactInventoryService(
        [
            RetainedArtifactFamily(
                "committed_builds",
                root,
                _HEX32,
                verify,
            )
        ]
    )
    return (
        database,
        root,
        evidence,
        ArtifactReconciliationService(database, inventory),
        revision_id,
    )


def _add_build(
    root: Path,
    evidence: dict[str, dict[str, Any]],
    artifact_id: str,
    *,
    project: str,
    revision_id: str,
    mtime_ns: int,
    payload: bytes,
    symlink_target: Path | None = None,
) -> None:
    path = root / artifact_id
    path.mkdir()
    (path / "payload.bin").write_bytes(payload)
    if symlink_target is not None:
        (path / "external-link").symlink_to(symlink_target)
    os.utime(path, ns=(mtime_ns, mtime_ns))
    evidence[artifact_id] = {
        "build_id": artifact_id,
        "project": project,
        "revision_id": revision_id,
        "manifest_sha256": artifact_id[0] * 64,
    }


def _policy(
    reconciliation_id: str,
    rules: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "format": ARTIFACT_RETENTION_POLICY_FORMAT,
        "reconciliation_id": reconciliation_id,
        "rules": rules,
    }


def _rule(
    classification: str,
    *,
    minimum_age_seconds: int = 0,
    minimum_retained_count: int = 0,
    protected_artifact_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "family": "committed_builds",
        "classification": classification,
        "minimum_age_seconds": minimum_age_seconds,
        "minimum_retained_count": minimum_retained_count,
        "protected_artifact_ids": protected_artifact_ids or [],
    }


def _tree_state(root: Path) -> list[tuple[str, int, int, bytes | None]]:
    state = []
    for path in sorted(root.rglob("*")):
        value = path.lstat()
        content = path.read_bytes() if path.is_file() and not path.is_symlink() else None
        state.append((str(path.relative_to(root)), value.st_mode, value.st_mtime_ns, content))
    return state


def test_dry_run_plan_is_deterministic_bounded_and_non_mutating(
    tmp_path: Path,
) -> None:
    database, root, evidence, reconciliation, revision_id = _fixture(tmp_path)
    as_of = 10_000 * _SECOND
    reachable_id = "1" * 32
    newest_id = "2" * 32
    old_a_id = "3" * 32
    old_b_id = "4" * 32
    protected_id = "5" * 32
    external = tmp_path / "external-secret.bin"
    external.write_bytes(b"x" * 4096)

    _add_build(
        root,
        evidence,
        reachable_id,
        project="demo",
        revision_id=revision_id,
        mtime_ns=as_of - 5_000 * _SECOND,
        payload=b"reachable",
    )
    _add_build(
        root,
        evidence,
        newest_id,
        project="removed",
        revision_id="missing",
        mtime_ns=as_of - 10 * _SECOND,
        payload=b"newest",
    )
    _add_build(
        root,
        evidence,
        old_a_id,
        project="removed",
        revision_id="missing",
        mtime_ns=as_of - 1_000 * _SECOND,
        payload=b"abc",
        symlink_target=external,
    )
    _add_build(
        root,
        evidence,
        old_b_id,
        project="removed",
        revision_id="missing",
        mtime_ns=as_of - 900 * _SECOND,
        payload=b"12345",
    )
    _add_build(
        root,
        evidence,
        protected_id,
        project="removed",
        revision_id="missing",
        mtime_ns=as_of - 2_000 * _SECOND,
        payload=b"protected",
    )
    stage = root / ".interrupted-stage"
    stage.mkdir()
    (stage / "partial.bin").write_bytes(b"stage")
    os.utime(stage, ns=(as_of - 2_000 * _SECOND,) * 2)
    external_link = root / "unrelated-link"
    external_link.symlink_to(external)
    os.utime(
        external_link,
        ns=(as_of - 100 * _SECOND,) * 2,
        follow_symlinks=False,
    )

    reconciliation_id = reconciliation.report()["reconciliation_id"]
    policy = _policy(
        reconciliation_id,
        [
            _rule(
                "orphaned",
                minimum_age_seconds=100,
                minimum_retained_count=1,
                protected_artifact_ids=[protected_id],
            ),
            _rule("staging", minimum_age_seconds=100),
            _rule("unknown", minimum_age_seconds=0),
        ],
    )
    before = _tree_state(root)
    planner = ArtifactRetentionPlanner(reconciliation)
    try:
        first = planner.plan(policy, as_of_unix_ns=as_of)
        second = planner.plan(policy, as_of_unix_ns=as_of)
    finally:
        database.close()

    assert first == second
    assert first["format"] == ARTIFACT_RETENTION_PLAN_FORMAT
    assert first["complete"] is True
    assert first["dry_run"] is True
    assert first["mutation"] == "none"
    assert len(first["plan_id"]) == 64
    selected_ids = {item.get("artifact_id") for item in first["entries"] if "artifact_id" in item}
    assert selected_ids == {old_a_id, old_b_id}
    assert reachable_id not in selected_ids
    assert newest_id not in selected_ids
    assert protected_id not in selected_ids
    assert first["aggregate"]["selected_entry_count"] == 4
    assert first["aggregate"]["projected_logical_bytes"] == 3 + 5 + 5
    old_a = next(item for item in first["entries"] if item.get("artifact_id") == old_a_id)
    assert old_a["symlinks"] == 1
    assert old_a["logical_bytes"] == 3
    assert str(root) not in json.dumps(first, sort_keys=True)
    assert str(external) not in json.dumps(first, sort_keys=True)
    assert before == _tree_state(root)


def test_planner_rejects_unsafe_and_stale_reconciliation(
    tmp_path: Path,
) -> None:
    database, root, evidence, reconciliation, _revision_id = _fixture(tmp_path)
    artifact_id = "a" * 32
    _add_build(
        root,
        evidence,
        artifact_id,
        project="removed",
        revision_id="missing",
        mtime_ns=1,
        payload=b"x",
    )
    reconciliation_id = reconciliation.report()["reconciliation_id"]
    planner = ArtifactRetentionPlanner(reconciliation)
    try:
        with pytest.raises(ValidationError) as unsafe:
            planner.plan(
                _policy(reconciliation_id, [_rule("reachable")]),
                as_of_unix_ns=10 * _SECOND,
            )
        assert unsafe.value.code == "ARTIFACT_RETENTION_UNSAFE_CLASSIFICATION"

        (root / "new-root-pollution").mkdir()
        with pytest.raises(ValidationError) as stale:
            planner.plan(
                _policy(reconciliation_id, [_rule("orphaned")]),
                as_of_unix_ns=10 * _SECOND,
            )
        assert stale.value.code == "ARTIFACT_RETENTION_STALE_RECONCILIATION"
    finally:
        database.close()


def test_planner_accepts_exact_limits_and_rejects_limit_plus_one(
    tmp_path: Path,
) -> None:
    database, root, evidence, reconciliation, _revision_id = _fixture(tmp_path)
    for index, character in enumerate(("a", "b", "c"), start=1):
        _add_build(
            root,
            evidence,
            character * 32,
            project="removed",
            revision_id="missing",
            mtime_ns=index,
            payload=b"x",
        )
    reconciliation_id = reconciliation.report()["reconciliation_id"]
    policy = _policy(reconciliation_id, [_rule("orphaned")])
    try:
        exact = ArtifactRetentionPlanner(
            reconciliation,
            max_plan_entries=3,
            max_scan_entries=12,
        ).plan(policy, as_of_unix_ns=10 * _SECOND)
        assert exact["aggregate"]["selected_entry_count"] == 3

        with pytest.raises(ValidationError) as selected_overflow:
            ArtifactRetentionPlanner(
                reconciliation,
                max_plan_entries=2,
            ).plan(policy, as_of_unix_ns=10 * _SECOND)
        assert selected_overflow.value.code == "ARTIFACT_RETENTION_PLAN_LIMIT_EXCEEDED"

        with pytest.raises(ValidationError) as scan_overflow:
            ArtifactRetentionPlanner(
                reconciliation,
                max_scan_entries=11,
            ).plan(policy, as_of_unix_ns=10 * _SECOND)
        assert scan_overflow.value.code == "ARTIFACT_RETENTION_SCAN_LIMIT_EXCEEDED"
    finally:
        database.close()
