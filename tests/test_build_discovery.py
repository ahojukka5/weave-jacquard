from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from weave_frontend.builds import (
    BUILD_CATALOG_FORMAT,
    BUILD_LIST_FORMAT,
    BuildDiscoveryService,
)
from weave_frontend.compiler import BUILD_KEY_FORMAT
from weave_frontend.errors import NotFoundError, ValidationError


class _Cursor:
    def __init__(self, row: dict[str, str] | None) -> None:
        self.row = row

    def fetchone(self) -> dict[str, str] | None:
        return self.row


class _Connection:
    def __init__(self, workspace: _Workspace) -> None:
        self.workspace = workspace

    def execute(self, statement: str, parameters: tuple[str, str]) -> _Cursor:
        assert "SELECT r.root_hash" in statement
        revision_id, project = parameters
        root_hash = self.workspace.revisions.get((project, revision_id))
        return _Cursor(None if root_hash is None else {"root_hash": root_hash})


class _Database:
    def __init__(self, workspace: _Workspace) -> None:
        self.connection = _Connection(workspace)


class _Workspace:
    def __init__(self, manifests: list[dict[str, Any]]) -> None:
        self.projects = {"demo", "other"}
        self.calls: list[str] = []
        self.revisions: dict[tuple[str, str], str] = {}
        for manifest in manifests:
            project = manifest.get("project")
            revision_id = manifest.get("revision_id")
            revision_hash = manifest.get("revision_hash")
            if all(isinstance(value, str) for value in (project, revision_id, revision_hash)):
                self.projects.add(str(project))
                self.revisions[(str(project), str(revision_id))] = str(revision_hash)
        self.db = _Database(self)

    def project_id(self, project: str) -> str:
        self.calls.append(project)
        if project not in self.projects:
            raise NotFoundError(f"project {project!r} not found")
        return f"project-{project}"


class _Bridge:
    def __init__(
        self,
        build_root: Path,
        manifests: dict[str, dict[str, Any]],
        failures: dict[str, Exception] | None = None,
    ) -> None:
        self.build_root = build_root
        self.workspace = _Workspace(list(manifests.values()))
        self.manifests = manifests
        self.failures = failures or {}
        self.calls: list[str] = []

    def get(self, build_id: str) -> dict[str, Any]:
        self.calls.append(build_id)
        failure = self.failures.get(build_id)
        if failure is not None:
            raise failure
        return dict(self.manifests[build_id])


def _id(index: int) -> str:
    return f"{index:032x}"


def _manifest(
    build_id: str,
    *,
    project: str = "demo",
    branch: str = "main",
    revision_id: str = "revision-1",
    revision_hash: str = "a" * 64,
    status: str = "succeeded",
    document: str = "main.weave",
    documents: list[str] | None = None,
    target: str = "native",
    build_key_format: str = "legacy-test-build-key-v1",
) -> dict[str, Any]:
    selected_documents = documents or [document]
    return {
        "format": "weave-frontend-build-manifest-v2",
        "build_key_format": build_key_format,
        "build_id": build_id,
        "status": status,
        "project": project,
        "branch": branch,
        "revision_id": revision_id,
        "revision_hash": revision_hash,
        "document": document,
        "documents": selected_documents,
        "target": target,
        "compiler_target": "x86_64-unknown-linux-gnu",
        "compiler_sha256": "b" * 64,
        "returncode": 0 if status == "succeeded" else 10,
        "compiler_diagnostics_protocol_valid": True,
        "compiler_manifest_protocol_valid": True,
        "artifacts": {
            "diagnostics": "diagnostics.json",
            "executable": "program" if status == "succeeded" else None,
        },
    }


def _current_manifest(
    *,
    project: str = "demo",
    branch: str = "main",
    revision_id: str = "revision-current",
    revision_hash: str = "a" * 64,
    documents: list[str] | None = None,
    target: str = "native",
) -> tuple[str, dict[str, Any]]:
    selected_documents = documents or ["main.weave"]
    source_entries: list[dict[str, str]] = []
    key_documents: list[dict[str, str]] = []
    artifact_hashes: dict[str, str] = {}
    for index, document in enumerate(selected_documents):
        relative = f"sources/{index:04d}-{document}"
        source_hash = hashlib.sha256(f"{index}:{document}".encode()).hexdigest()
        source_entries.append(
            {
                "document": document,
                "source": relative,
                "node_map": f"source-maps/{index:04d}-{document}.json",
                "source_sha256": source_hash,
            }
        )
        key_documents.append({"document": document, "source_sha256": source_hash})
        artifact_hashes[relative] = source_hash

    payload = {
        "format": BUILD_KEY_FORMAT,
        "evidence_profile": "none",
        "revision_hash": revision_hash,
        "revision_id": revision_id,
        "documents": key_documents,
        "compiler_sha256": "b" * 64,
        "compiler_output_limit_bytes": 4 * 1024 * 1024,
        "target": target,
    }
    build_id = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:32]
    manifest = _manifest(
        build_id,
        project=project,
        branch=branch,
        revision_id=revision_id,
        revision_hash=revision_hash,
        document=selected_documents[0],
        documents=selected_documents,
        target=target,
        build_key_format=BUILD_KEY_FORMAT,
    )
    manifest.update(
        {
            "evidence_profile": "none",
            "source_sha256": key_documents[0]["source_sha256"],
            "sources": source_entries,
            "artifact_sha256": artifact_hashes,
            "compiler_output_limit_bytes": 4 * 1024 * 1024,
            "timed_out": False,
            "output_limited": False,
        }
    )
    return build_id, manifest


def _candidate(root: Path, build_id: str) -> None:
    directory = root / build_id
    directory.mkdir()
    (directory / "manifest.json").write_text("{}\n", encoding="utf-8")


def test_discovery_pages_verified_candidates_and_preserves_catalog(tmp_path: Path) -> None:
    build_ids = [_id(index) for index in range(4)]
    for build_id in build_ids:
        _candidate(tmp_path, build_id)
    (tmp_path / ".temporary-build").mkdir()
    missing_manifest = tmp_path / _id(99)
    missing_manifest.mkdir()

    manifests = {
        build_ids[0]: _manifest(build_ids[0]),
        build_ids[1]: _manifest(build_ids[1], project="other"),
        build_ids[2]: _manifest(
            build_ids[2],
            branch="feature",
            revision_id="revision-2",
            status="failed",
            document="lib.weave",
            target="wasm32-wasi",
        ),
        build_ids[3]: _manifest(build_ids[3]),
    }
    bridge = _Bridge(
        tmp_path,
        manifests,
        failures={
            build_ids[3]: ValidationError(
                "CORRUPT_BUILD_ARTIFACT",
                "checksum mismatch",
            )
        },
    )
    service = BuildDiscoveryService(bridge)

    first = service.page("demo", limit=2)
    second = service.page(
        "demo",
        start_after_build_id=first["next_after_build_id"],
        catalog_id=first["catalog_id"],
        limit=2,
    )

    assert first["format"] == BUILD_LIST_FORMAT
    assert first["catalog_format"] == BUILD_CATALOG_FORMAT
    assert len(first["catalog_id"]) == 64
    assert first["catalog_scope"] == "build-root-membership"
    assert first["catalog_build_count"] == 4
    assert first["scanned_count"] == 2
    assert first["returned_count"] == 1
    assert first["filtered_count"] == 1
    assert first["rejected_count"] == 0
    assert first["has_more"] is True
    assert first["next_after_build_id"] == build_ids[1]
    assert first["builds"][0]["build_id"] == build_ids[0]
    assert first["builds"][0]["revision_provenance_verified"] is True
    assert first["builds"][0]["build_key_verified"] is False
    assert first["builds"][0]["executable_available"] is True
    assert "artifact_paths" not in first["builds"][0]
    assert "build_directory" not in first["builds"][0]

    assert second["catalog_id"] == first["catalog_id"]
    assert second["scanned_count"] == 2
    assert second["returned_count"] == 1
    assert second["filtered_count"] == 0
    assert second["rejected_builds"] == [
        {"build_id": build_ids[3], "code": "CORRUPT_BUILD_ARTIFACT"}
    ]
    assert second["has_more"] is False
    assert second["next_after_build_id"] is None
    assert second["builds"][0]["status"] == "failed"
    assert second["builds"][0]["executable_available"] is False
    assert bridge.calls == build_ids
    assert bridge.workspace.calls == ["demo", "demo"]


def test_discovery_filters_verified_summaries(tmp_path: Path) -> None:
    build_ids = [_id(index) for index in range(3)]
    for build_id in build_ids:
        _candidate(tmp_path, build_id)
    bridge = _Bridge(
        tmp_path,
        {
            build_ids[0]: _manifest(build_ids[0]),
            build_ids[1]: _manifest(
                build_ids[1],
                branch="feature",
                revision_id="revision-2",
                status="failed",
                document="lib.weave",
                documents=["lib.weave", "support.weave"],
                target="wasm32-wasi",
            ),
            build_ids[2]: _manifest(
                build_ids[2],
                branch="feature",
                revision_id="revision-3",
                document="main.weave",
                documents=["main.weave", "support.weave"],
                target="native",
            ),
        },
    )
    service = BuildDiscoveryService(bridge)

    result = service.page(
        "demo",
        branch="feature",
        status="failed",
        revision_id="revision-2",
        document="support.weave",
        target="wasm32-wasi",
        limit=10,
    )

    assert result["filters"] == {
        "branch": "feature",
        "revision_id": "revision-2",
        "status": "failed",
        "document": "support.weave",
        "target": "wasm32-wasi",
    }
    assert result["returned_count"] == 1
    assert result["filtered_count"] == 2
    assert result["builds"][0]["build_id"] == build_ids[1]
    assert result["builds"][0]["documents"] == ["lib.weave", "support.weave"]


def test_current_build_key_and_revision_provenance_are_verified(tmp_path: Path) -> None:
    build_id, manifest = _current_manifest(documents=["main.weave", "lib.weave"])
    _candidate(tmp_path, build_id)
    bridge = _Bridge(tmp_path, {build_id: manifest})

    result = BuildDiscoveryService(bridge).page("demo")

    assert result["returned_count"] == 1
    assert result["builds"][0]["revision_provenance_verified"] is True
    assert result["builds"][0]["build_key_format"] == BUILD_KEY_FORMAT
    assert result["builds"][0]["evidence_profile"] == "none"
    assert result["builds"][0]["build_key_verified"] is True


def test_discovery_rejects_tampered_current_build_key(tmp_path: Path) -> None:
    build_id, manifest = _current_manifest()
    manifest["target"] = "wasm32-wasi"
    _candidate(tmp_path, build_id)

    result = BuildDiscoveryService(_Bridge(tmp_path, {build_id: manifest})).page("demo")

    assert result["builds"] == []
    assert result["rejected_builds"] == [{"build_id": build_id, "code": "BUILD_KEY_MISMATCH"}]


def test_discovery_rejects_tampered_source_metadata(tmp_path: Path) -> None:
    build_id, manifest = _current_manifest()
    source_path = manifest["sources"][0]["source"]
    manifest["artifact_sha256"][source_path] = "c" * 64
    _candidate(tmp_path, build_id)

    result = BuildDiscoveryService(_Bridge(tmp_path, {build_id: manifest})).page("demo")

    assert result["builds"] == []
    assert result["rejected_builds"] == [
        {"build_id": build_id, "code": "BUILD_SOURCE_METADATA_MISMATCH"}
    ]


def test_discovery_rejects_missing_revision_provenance(tmp_path: Path) -> None:
    build_id = _id(1)
    manifest = _manifest(build_id)
    _candidate(tmp_path, build_id)
    bridge = _Bridge(tmp_path, {build_id: manifest})
    bridge.workspace.revisions.clear()

    result = BuildDiscoveryService(bridge).page("demo")

    assert result["rejected_builds"] == [{"build_id": build_id, "code": "BUILD_REVISION_NOT_FOUND"}]


def test_discovery_rejects_revision_hash_mismatch(tmp_path: Path) -> None:
    build_id = _id(1)
    manifest = _manifest(build_id)
    _candidate(tmp_path, build_id)
    bridge = _Bridge(tmp_path, {build_id: manifest})
    bridge.workspace.revisions[("demo", "revision-1")] = "c" * 64

    result = BuildDiscoveryService(bridge).page("demo")

    assert result["rejected_builds"] == [
        {"build_id": build_id, "code": "BUILD_REVISION_HASH_MISMATCH"}
    ]


def test_discovery_rejects_changed_catalog_membership(tmp_path: Path) -> None:
    first_id = _id(1)
    _candidate(tmp_path, first_id)
    bridge = _Bridge(tmp_path, {first_id: _manifest(first_id)})
    service = BuildDiscoveryService(bridge)
    first = service.page("demo", limit=1)

    second_id = _id(2)
    _candidate(tmp_path, second_id)
    bridge.manifests[second_id] = _manifest(second_id)

    with pytest.raises(ValidationError) as raised:
        service.page(
            "demo",
            start_after_build_id=first_id,
            catalog_id=first["catalog_id"],
            limit=1,
        )
    assert raised.value.code == "STALE_BUILD_CATALOG"
    assert bridge.calls == [first_id]


def test_discovery_rejects_invalid_summary_without_returning_it(tmp_path: Path) -> None:
    build_id = _id(1)
    _candidate(tmp_path, build_id)
    invalid = _manifest(build_id)
    invalid["documents"] = []
    bridge = _Bridge(tmp_path, {build_id: invalid})

    result = BuildDiscoveryService(bridge).page("demo")

    assert result["builds"] == []
    assert result["rejected_builds"] == [{"build_id": build_id, "code": "INVALID_BUILD_MANIFEST"}]


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"limit": 0}, "INVALID_BUILD_LIST_LIMIT"),
        ({"limit": 201}, "INVALID_BUILD_LIST_LIMIT"),
        ({"limit": True}, "INVALID_BUILD_LIST_LIMIT"),
        ({"status": "unknown"}, "INVALID_BUILD_LIST_FILTER"),
        ({"branch": ""}, "INVALID_BUILD_LIST_FILTER"),
        ({"start_after_build_id": "bad"}, "INVALID_BUILD_LIST_CURSOR"),
        ({"catalog_id": "bad"}, "INVALID_BUILD_CATALOG_ID"),
        ({"catalog_id": 3}, "INVALID_BUILD_CATALOG_ID"),
    ],
)
def test_discovery_validates_requests(
    tmp_path: Path,
    kwargs: dict[str, Any],
    code: str,
) -> None:
    bridge = _Bridge(tmp_path, {})
    with pytest.raises(ValidationError) as raised:
        BuildDiscoveryService(bridge).page("demo", **kwargs)
    assert raised.value.code == code


def test_discovery_requires_existing_project(tmp_path: Path) -> None:
    bridge = _Bridge(tmp_path, {})
    with pytest.raises(NotFoundError, match="missing"):
        BuildDiscoveryService(bridge).page("missing")
