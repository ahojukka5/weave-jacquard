from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from weave_frontend.release_compatibility import (
    COMPATIBILITY_POLICY_FORMAT,
    RELEASE_COMPATIBILITY_REVIEW_FORMAT,
    ReleaseCompatibilityError,
    review_release_compatibility,
    write_review_report,
)

ROOT = Path(__file__).resolve().parents[1]


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _tool_manifest(
    *,
    description: str = "Tool alpha",
    include_optional: bool = False,
) -> dict[str, object]:
    properties: dict[str, object] = {}
    if include_optional:
        properties["limit"] = {"type": "integer", "default": 10}
    tool = {
        "name": "alpha",
        "title": None,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": [],
            "additionalProperties": False,
        },
        "output_schema": None,
        "annotations": None,
        "icons": None,
        "meta": None,
    }
    identity_payload = {
        "format": "weave-jacquard-tool-manifest-v2",
        "tools": [tool],
        "tool_names": ["alpha"],
        "tool_count": 1,
    }
    identity = hashlib.sha256(_canonical_bytes(identity_payload)).hexdigest()
    return {**identity_payload, "tool_manifest_id": identity}


def _application_manifest(tool_manifest: dict[str, object]) -> dict[str, object]:
    identity_payload = {
        "format": "weave-jacquard-application-v2",
        "capabilities": [
            {
                "name": "base",
                "module": "example.base",
                "depends_on": [],
            }
        ],
        "tool_manifest_id": tool_manifest["tool_manifest_id"],
        "tool_count": 1,
        "configuration_variables": ["WEAVE_DB"],
    }
    identity = hashlib.sha256(_canonical_bytes(identity_payload)).hexdigest()
    return {**identity_payload, "application_id": identity}


def _write_evidence(
    root: Path,
    *,
    git_sha: str,
    tool_manifest: dict[str, object],
) -> Path:
    root.mkdir()
    manifest_root = root / "manifests"
    manifest_root.mkdir()
    application_manifest = _application_manifest(tool_manifest)
    capability_manifest = {
        "format": "weave-jacquard-capability-manifest-v1",
        "capabilities": [{"name": "base"}],
    }
    documents = {
        "tool": ("tool-manifest.json", tool_manifest),
        "application": ("application-manifest.json", application_manifest),
        "capability": ("capability-manifest.json", capability_manifest),
    }
    entries = []
    for kind, (name, document) in documents.items():
        payload = _canonical_bytes(document)
        path = manifest_root / name
        path.write_bytes(payload)
        entry = {
            "kind": kind,
            "path": f"manifests/{name}",
            "format": document["format"],
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        if kind == "tool":
            entry["identity"] = tool_manifest["tool_manifest_id"]
        elif kind == "application":
            entry["identity"] = application_manifest["application_id"]
        entries.append(entry)

    completion = {
        "format": "weave-jacquard-qualification-complete-v1",
        "status": "passed",
        "git_sha": git_sha,
    }
    (root / "qualification-complete.json").write_bytes(_canonical_bytes(completion))
    index = {
        "format": "weave-jacquard-release-manifest-index-v1",
        "qualification_git_sha": git_sha,
        "tool_manifest_id": tool_manifest["tool_manifest_id"],
        "application_id": application_manifest["application_id"],
        "manifest_count": len(entries),
        "manifests": entries,
    }
    (root / "manifest-index.json").write_bytes(_canonical_bytes(index))
    return root


def _write_policy(path: Path, report: dict[str, object]) -> Path:
    reviews = []
    for decision in report["decisions"]:
        if decision["change_count"] == 0:
            continue
        reviews.append(
            {
                "manifest": decision["manifest"],
                "compatibility_diff_id": decision["compatibility_diff_id"],
                "classification": decision["classification"],
                "decision": "accept",
                "reason": "Reviewed as an intentional public contract change.",
            }
        )
    policy = {
        "format": COMPATIBILITY_POLICY_FORMAT,
        "reviewed_by": "release-reviewer",
        "reviewed_at": "2026-08-03T11:00:00Z",
        "reviews": reviews,
    }
    path.write_bytes(_canonical_bytes(policy))
    return path


def test_identical_release_evidence_is_accepted_without_policy(
    tmp_path: Path,
) -> None:
    tool_manifest = _tool_manifest()
    previous = _write_evidence(
        tmp_path / "previous",
        git_sha="a" * 40,
        tool_manifest=tool_manifest,
    )
    current = _write_evidence(
        tmp_path / "current",
        git_sha="b" * 40,
        tool_manifest=tool_manifest,
    )

    first = review_release_compatibility(previous, current)
    second = review_release_compatibility(previous, current)

    assert first == second
    assert first["format"] == RELEASE_COMPATIBILITY_REVIEW_FORMAT
    assert first["status"] == "accepted"
    assert first["classification"] == "identity-only"
    assert {item["decision"] for item in first["decisions"]} == {"unchanged"}


def test_changed_release_requires_exact_reviewed_policy(tmp_path: Path) -> None:
    previous = _write_evidence(
        tmp_path / "previous",
        git_sha="a" * 40,
        tool_manifest=_tool_manifest(),
    )
    current = _write_evidence(
        tmp_path / "current",
        git_sha="b" * 40,
        tool_manifest=_tool_manifest(include_optional=True),
    )

    unreviewed = review_release_compatibility(previous, current)

    assert unreviewed["status"] == "review-required"
    assert unreviewed["classification"] == "behavior-review-required"
    policy = _write_policy(tmp_path / "policy.json", unreviewed)

    accepted = review_release_compatibility(
        previous,
        current,
        policy_path=policy,
    )

    assert accepted["status"] == "accepted"
    assert accepted["policy"]["reviewed_by"] == "release-reviewer"
    assert len(accepted["policy"]["sha256"]) == 64
    changed = [item for item in accepted["decisions"] if item["change_count"] != 0]
    assert changed
    assert {item["decision"] for item in changed} == {"accepted"}


def test_stale_policy_does_not_approve_changed_release(tmp_path: Path) -> None:
    previous = _write_evidence(
        tmp_path / "previous",
        git_sha="a" * 40,
        tool_manifest=_tool_manifest(),
    )
    current = _write_evidence(
        tmp_path / "current",
        git_sha="b" * 40,
        tool_manifest=_tool_manifest(description="Updated documentation"),
    )
    unreviewed = review_release_compatibility(previous, current)
    policy_path = _write_policy(tmp_path / "policy.json", unreviewed)
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["reviews"][0]["compatibility_diff_id"] = "0" * 64
    policy_path.write_bytes(_canonical_bytes(policy))

    reviewed = review_release_compatibility(
        previous,
        current,
        policy_path=policy_path,
    )

    assert reviewed["status"] == "review-required"
    assert "review-required" in {item["decision"] for item in reviewed["decisions"]}


def test_tampered_retained_manifest_fails_closed(tmp_path: Path) -> None:
    previous = _write_evidence(
        tmp_path / "previous",
        git_sha="a" * 40,
        tool_manifest=_tool_manifest(),
    )
    current = _write_evidence(
        tmp_path / "current",
        git_sha="b" * 40,
        tool_manifest=_tool_manifest(),
    )
    path = current / "manifests" / "tool-manifest.json"
    path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ReleaseCompatibilityError, match="byte count"):
        review_release_compatibility(previous, current)


def test_review_report_is_immutable_canonical_json(tmp_path: Path) -> None:
    tool_manifest = _tool_manifest()
    previous = _write_evidence(
        tmp_path / "previous",
        git_sha="a" * 40,
        tool_manifest=tool_manifest,
    )
    current = _write_evidence(
        tmp_path / "current",
        git_sha="b" * 40,
        tool_manifest=tool_manifest,
    )
    report = review_release_compatibility(previous, current)
    output = tmp_path / "review.json"

    write_review_report(output, report)

    assert output.read_bytes() == _canonical_bytes(report)
    with pytest.raises(ReleaseCompatibilityError, match="already exists"):
        write_review_report(output, report)


def test_release_qualification_retains_review_before_checksums() -> None:
    source = (ROOT / "scripts" / "qualify-release.sh").read_text(encoding="utf-8")

    assert "WEAVE_PREVIOUS_RELEASE_EVIDENCE" in source
    assert "WEAVE_COMPATIBILITY_POLICY" in source
    assert "compatibility-review.json" in source
    assert source.index("weave_frontend.release_compatibility") < source.index(
        'qualification.py" checksums'
    )
    assert "review_status" in source
