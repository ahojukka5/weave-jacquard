"""In-process byte targets. Unexpected exceptions intentionally escape."""

from __future__ import annotations

import json
from pathlib import Path

from weave_frontend.compiler import (
    CompilerArtifactMixin,
    WeavecCapabilities,
    collect_build_diagnostics,
    validate_compiler_manifest,
)
from weave_frontend.errors import WeaveFrontendError
from weave_frontend.manifest_compatibility import ManifestCompatibilityError, compare_manifests
from weave_frontend.merges import MergeCandidateTestBatchService
from weave_frontend.retained_artifact_io import RetainedArtifactReadError, read_bounded_regular_json
from weave_frontend.sexpr import parse_source, render_node, validate_tree
from weave_frontend.snapshot_codec import (
    SnapshotIntegrityError,
    canonical_json,
    decode_snapshot,
    hash_value,
)
from weave_frontend.source_map import render_with_node_map, smallest_node_for_span
from weave_frontend.test_batches import TestBatchService
from weave_frontend.test_runs import TestRunService
from weave_frontend.verified_database_backup import DatabaseBackupService
from weave_frontend.verified_merge_candidate_build import MergeCandidateBuildService

MAX_CASE_BYTES = 16_384
TREE = {"id": "n_root", "kind": "list", "children": []}
READERS = {
    "retained_json": lambda path: read_bounded_regular_json(path, max_bytes=MAX_CASE_BYTES),
    "candidate_build": MergeCandidateBuildService._read_manifest,
    "candidate_qualification": MergeCandidateTestBatchService._read_manifest,
    "backup": DatabaseBackupService._read_manifest,
    "test_run": TestRunService._read_json,
    "test_batch": TestBatchService._read_json,
}
TARGETS = (
    "capabilities",
    "compatibility",
    "node_map",
    "sexpr",
    "snapshot",
    "compiler_manifest",
    "compiler_diagnostics",
    "build",
    *READERS,
)


def replay(target: str, payload: bytes, directory: Path) -> str:
    """Return a stable acceptance/error category; never hide a crash."""
    if len(payload) > MAX_CASE_BYTES:
        raise ValueError("case exceeds harness byte ceiling")
    path = directory / "manifest.json"
    try:
        if target == "sexpr":
            # UTF-8 decoding belongs to the transport before parse_source.
            try:
                source = payload.decode("utf-8")
            except UnicodeError:
                return "transport:utf8"
            root = parse_source(source)
            rendered = render_node(root)
            assert render_node(parse_source(rendered)) == rendered
        elif target == "snapshot":
            decoded = decode_snapshot(payload, expected_hash=hash_value(TREE))
            assert decoded.canonical_json == canonical_json(TREE)
            assert hash_value(json.loads(decoded.canonical_json)) == decoded.ast_hash
        else:
            path.write_bytes(payload)
            if target in {"capabilities", "compatibility", "node_map"}:
                value = read_bounded_regular_json(path, max_bytes=MAX_CASE_BYTES)
                if target == "capabilities":
                    WeavecCapabilities._validate(value)
                elif target == "compatibility":
                    if not isinstance(value, dict):
                        raise ManifestCompatibilityError("manifest root must be an object")
                    assert compare_manifests(value, value)["change_count"] == 0
                else:
                    validate_tree(value)
                    source, node_map = render_with_node_map(
                        value, revision_id="fixture", document="source.weave"
                    )
                    assert (
                        smallest_node_for_span(
                            node_map, start_byte=0, end_byte=len(source.encode()) - 1
                        )
                        == value["id"]
                    )
                return "accepted"
            if target == "compiler_manifest":
                _, errors = validate_compiler_manifest(
                    path,
                    expected_sources=[],
                    expected_output=directory / "program",
                    requested_target=None,
                    returncode=0,
                    diagnostics_status="succeeded",
                )
                return "protocol:rejected" if errors else "accepted"
            if target == "compiler_diagnostics":
                value, valid = collect_build_diagnostics(
                    path,
                    returncode=0,
                    timed_out=False,
                    stdout="",
                    stderr="",
                    canonical_sources=[(directory / "source.weave", {"nodes": []})],
                )
                assert str(directory) not in json.dumps(value["protocol_errors"])
                return "protocol:accepted" if valid else "protocol:rejected"
            if target == "build":
                CompilerArtifactMixin._read_verified_manifest(directory)
            else:
                READERS[target](path)
        return "accepted"
    except (
        WeaveFrontendError,
        SnapshotIntegrityError,
        RetainedArtifactReadError,
        ManifestCompatibilityError,
    ) as error:
        assert str(directory) not in str(error)
        return f"rejected:{getattr(error, 'code', type(error).__name__)}"
