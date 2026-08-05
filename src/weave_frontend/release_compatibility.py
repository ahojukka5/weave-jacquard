"""Review retained release manifests against an explicit compatibility policy."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .manifest_compatibility import (
    ManifestCompatibilityError,
    compare_application_manifests,
    compare_tool_manifests,
)

RELEASE_COMPATIBILITY_REVIEW_FORMAT = "weave-jacquard-release-compatibility-review-v1"
COMPATIBILITY_POLICY_FORMAT = "weave-jacquard-compatibility-policy-v1"
RELEASE_MANIFEST_INDEX_FORMAT = "weave-jacquard-release-manifest-index-v1"
QUALIFICATION_COMPLETION_FORMAT = "weave-jacquard-qualification-complete-v1"
MAX_EVIDENCE_JSON_BYTES = 16 * 1024 * 1024
MAX_POLICY_BYTES = 1024 * 1024
_CLASSIFICATION_ORDER = {
    "identity-only": 0,
    "documentation-only": 1,
    "additive-compatible": 2,
    "behavior-review-required": 3,
    "breaking": 4,
}
_MANIFEST_PATHS = {
    "tool": "manifests/tool-manifest.json",
    "application": "manifests/application-manifest.json",
    "capability": "manifests/capability-manifest.json",
}


class ReleaseCompatibilityError(RuntimeError):
    """Raised when retained release evidence cannot be reviewed safely."""


def _canonical_bytes(value: Any) -> bytes:
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


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _require_sha256(value: Any, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ReleaseCompatibilityError(f"{label} must be a lowercase SHA-256 identity")
    return value


def _read_object(
    path: Path,
    *,
    label: str,
    limit: int = MAX_EVIDENCE_JSON_BYTES,
) -> tuple[Mapping[str, Any], bytes]:
    if path.is_symlink():
        raise ReleaseCompatibilityError(f"{label} must not be a symlink")
    try:
        with path.open("rb") as stream:
            payload = stream.read(limit + 1)
    except OSError as exc:
        reason = exc.strerror or type(exc).__name__
        raise ReleaseCompatibilityError(f"cannot read {label}: {reason}") from exc
    if len(payload) > limit:
        raise ReleaseCompatibilityError(f"{label} exceeds {limit} bytes")
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseCompatibilityError(f"{label} is not valid JSON") from exc
    if not isinstance(document, Mapping):
        raise ReleaseCompatibilityError(f"{label} must contain a JSON object")
    return document, payload


def _entry_path(root: Path, value: Any, *, label: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ReleaseCompatibilityError(f"{label} path must be a non-empty string")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ReleaseCompatibilityError(f"{label} path escapes the evidence directory")
    resolved = (root / relative).resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise ReleaseCompatibilityError(f"{label} path escapes the evidence directory")
    return resolved


def _load_evidence(root: Path, *, label: str) -> dict[str, Any]:
    candidate = root.expanduser()
    if candidate.is_symlink():
        raise ReleaseCompatibilityError(f"{label} evidence must not be a symlink")
    evidence_root = candidate.resolve()
    if not evidence_root.is_dir():
        raise ReleaseCompatibilityError(f"{label} evidence must be a directory")

    completion, _ = _read_object(
        evidence_root / "qualification-complete.json",
        label=f"{label} qualification completion",
    )
    if completion.get("format") != QUALIFICATION_COMPLETION_FORMAT:
        raise ReleaseCompatibilityError(f"{label} qualification completion format is unsupported")
    if completion.get("status") != "passed":
        raise ReleaseCompatibilityError(f"{label} qualification did not pass")
    git_sha = completion.get("git_sha")
    if not isinstance(git_sha, str) or not git_sha:
        raise ReleaseCompatibilityError(f"{label} qualification git_sha is missing")

    index, _ = _read_object(
        evidence_root / "manifest-index.json",
        label=f"{label} manifest index",
    )
    if index.get("format") != RELEASE_MANIFEST_INDEX_FORMAT:
        raise ReleaseCompatibilityError(f"{label} manifest index format is unsupported")
    if index.get("qualification_git_sha") != git_sha:
        raise ReleaseCompatibilityError(
            f"{label} manifest index does not match qualification git_sha"
        )
    entries = index.get("manifests")
    if not isinstance(entries, Sequence) or isinstance(
        entries,
        (str, bytes, bytearray),
    ):
        raise ReleaseCompatibilityError(f"{label} manifest entries must be a list")
    if index.get("manifest_count") != len(entries):
        raise ReleaseCompatibilityError(f"{label} manifest_count does not match")

    by_kind: dict[str, Mapping[str, Any]] = {}
    documents: dict[str, Mapping[str, Any]] = {}
    for position, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise ReleaseCompatibilityError(f"{label} manifest entry {position} must be an object")
        kind = entry.get("kind")
        if kind not in _MANIFEST_PATHS or kind in by_kind:
            raise ReleaseCompatibilityError(f"{label} manifest entry {position} kind is invalid")
        expected_path = _MANIFEST_PATHS[kind]
        if entry.get("path") != expected_path:
            raise ReleaseCompatibilityError(f"{label} {kind} manifest path is not canonical")
        path = _entry_path(evidence_root, expected_path, label=f"{label} {kind}")
        document, payload = _read_object(path, label=f"{label} {kind} manifest")
        if entry.get("bytes") != len(payload):
            raise ReleaseCompatibilityError(f"{label} {kind} manifest byte count does not match")
        if entry.get("sha256") != _sha256(payload):
            raise ReleaseCompatibilityError(f"{label} {kind} manifest checksum does not match")
        if entry.get("format") != document.get("format"):
            raise ReleaseCompatibilityError(f"{label} {kind} manifest format does not match")
        by_kind[kind] = entry
        documents[kind] = document

    if set(by_kind) != set(_MANIFEST_PATHS):
        raise ReleaseCompatibilityError(
            f"{label} evidence must contain tool, application, and capability manifests"
        )
    if documents["capability"].get("format") != ("weave-jacquard-capability-manifest-v1"):
        raise ReleaseCompatibilityError(f"{label} capability manifest format is unsupported")

    identities = {
        "tool": ("tool_manifest_id", "tool_manifest_id"),
        "application": ("application_id", "application_id"),
    }
    for kind, (field, index_field) in identities.items():
        identity = _require_sha256(
            documents[kind].get(field),
            label=f"{label} {field}",
        )
        if by_kind[kind].get("identity") != identity:
            raise ReleaseCompatibilityError(
                f"{label} {kind} manifest identity does not match its entry"
            )
        if index.get(index_field) != identity:
            raise ReleaseCompatibilityError(
                f"{label} {kind} manifest identity does not match the index"
            )

    return {
        "git_sha": git_sha,
        "tool": documents["tool"],
        "application": documents["application"],
    }


def _load_policy(path: Path) -> tuple[Mapping[str, Any], str]:
    policy, _ = _read_object(
        path.expanduser(),
        label="compatibility policy",
        limit=MAX_POLICY_BYTES,
    )
    if set(policy) != {"format", "reviewed_by", "reviewed_at", "reviews"}:
        raise ReleaseCompatibilityError("compatibility policy has invalid fields")
    if policy.get("format") != COMPATIBILITY_POLICY_FORMAT:
        raise ReleaseCompatibilityError("compatibility policy format is unsupported")
    for field in ("reviewed_by", "reviewed_at"):
        value = policy.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ReleaseCompatibilityError(f"compatibility policy {field} is required")
    reviews = policy.get("reviews")
    if not isinstance(reviews, Sequence) or isinstance(
        reviews,
        (str, bytes, bytearray),
    ):
        raise ReleaseCompatibilityError("compatibility policy reviews must be a list")

    seen: set[str] = set()
    required_fields = {
        "manifest",
        "compatibility_diff_id",
        "classification",
        "decision",
        "reason",
    }
    for position, review in enumerate(reviews):
        if not isinstance(review, Mapping) or set(review) != required_fields:
            raise ReleaseCompatibilityError(
                f"compatibility policy review {position} has invalid fields"
            )
        manifest = review.get("manifest")
        if manifest not in {"tool", "application"} or manifest in seen:
            raise ReleaseCompatibilityError(
                f"compatibility policy review {position} manifest is invalid"
            )
        seen.add(manifest)
        _require_sha256(
            review.get("compatibility_diff_id"),
            label=f"compatibility policy review {position} diff identity",
        )
        if review.get("classification") not in _CLASSIFICATION_ORDER:
            raise ReleaseCompatibilityError(
                f"compatibility policy review {position} classification is unsupported"
            )
        if review.get("decision") != "accept":
            raise ReleaseCompatibilityError(
                f"compatibility policy review {position} decision must be 'accept'"
            )
        reason = review.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ReleaseCompatibilityError(
                f"compatibility policy review {position} reason is required"
            )
    return policy, _sha256(_canonical_bytes(policy))


def review_release_compatibility(
    previous_evidence: Path,
    current_evidence: Path,
    *,
    policy_path: Path | None = None,
) -> dict[str, Any]:
    """Compare two retained releases and apply exact reviewed dispositions."""

    previous = _load_evidence(previous_evidence, label="previous")
    current = _load_evidence(current_evidence, label="current")
    try:
        reports = {
            "tool": compare_tool_manifests(previous["tool"], current["tool"]),
            "application": compare_application_manifests(
                previous["application"],
                current["application"],
            ),
        }
    except ManifestCompatibilityError as exc:
        raise ReleaseCompatibilityError(str(exc)) from exc

    policy: Mapping[str, Any] | None = None
    policy_sha256: str | None = None
    reviews: dict[str, Mapping[str, Any]] = {}
    if policy_path is not None:
        policy, policy_sha256 = _load_policy(policy_path)
        reviews = {review["manifest"]: review for review in policy["reviews"]}

    decisions = []
    changed_manifests: set[str] = set()
    for manifest in ("tool", "application"):
        report = reports[manifest]
        changed = report["change_count"] != 0
        review = reviews.get(manifest)
        reason = None
        if not changed:
            decision = "unchanged"
        else:
            changed_manifests.add(manifest)
            if review is not None and (
                review["compatibility_diff_id"] == report["compatibility_diff_id"]
                and review["classification"] == report["classification"]
            ):
                decision = "accepted"
                reason = review["reason"]
            else:
                decision = "review-required"
        decisions.append(
            {
                "manifest": manifest,
                "classification": report["classification"],
                "compatibility_diff_id": report["compatibility_diff_id"],
                "change_count": report["change_count"],
                "decision": decision,
                "reason": reason,
            }
        )

    stale = set(reviews) - changed_manifests
    if stale:
        names = ", ".join(sorted(stale))
        raise ReleaseCompatibilityError(
            f"compatibility policy contains stale review entries: {names}"
        )
    status = (
        "accepted"
        if all(item["decision"] != "review-required" for item in decisions)
        else "review-required"
    )
    classification = max(
        (report["classification"] for report in reports.values()),
        key=_CLASSIFICATION_ORDER.__getitem__,
    )
    policy_summary = None
    if policy is not None:
        policy_summary = {
            "format": policy["format"],
            "reviewed_by": policy["reviewed_by"],
            "reviewed_at": policy["reviewed_at"],
            "sha256": policy_sha256,
        }
    payload = {
        "format": RELEASE_COMPATIBILITY_REVIEW_FORMAT,
        "status": status,
        "classification": classification,
        "previous_git_sha": previous["git_sha"],
        "current_git_sha": current["git_sha"],
        "policy": policy_summary,
        "decisions": decisions,
        "reports": reports,
    }
    return {
        **payload,
        "release_compatibility_review_id": _sha256(_canonical_bytes(payload)),
    }


def write_review_report(path: Path, report: Mapping[str, Any]) -> None:
    """Write one immutable canonical release compatibility report."""

    candidate = path.expanduser()
    if candidate.exists() or candidate.is_symlink():
        raise ReleaseCompatibilityError("compatibility review output already exists")
    if not candidate.parent.resolve().is_dir():
        raise ReleaseCompatibilityError("compatibility review output parent must exist")
    candidate.write_bytes(_canonical_bytes(report))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="weave-release-compatibility")
    parser.add_argument("previous_evidence", type=Path)
    parser.add_argument("current_evidence", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        report = review_release_compatibility(
            args.previous_evidence,
            args.current_evidence,
            policy_path=args.policy,
        )
        if args.output is None:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            write_review_report(args.output, report)
    except ReleaseCompatibilityError as exc:
        payload = {
            "ok": False,
            "error": {
                "code": "RELEASE_COMPATIBILITY_ERROR",
                "message": str(exc),
            },
        }
        print(json.dumps(payload, indent=2, sort_keys=True), file=sys.stderr)
        raise SystemExit(2) from None
    if report["status"] != "accepted":
        raise SystemExit(3)


__all__ = [
    "COMPATIBILITY_POLICY_FORMAT",
    "RELEASE_COMPATIBILITY_REVIEW_FORMAT",
    "ReleaseCompatibilityError",
    "main",
    "review_release_compatibility",
    "write_review_report",
]


if __name__ == "__main__":
    main()
