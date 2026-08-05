from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "retain-public-manifests.py"


def _load_helper() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "jacquard_release_manifests",
        HELPER,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


release_manifests = _load_helper()


def _qualified_output(tmp_path: Path) -> Path:
    output = tmp_path / "qualification"
    output.mkdir()
    (output / "qualification-complete.json").write_text(
        json.dumps(
            {
                "format": release_manifests.QUALIFICATION_COMPLETION_FORMAT,
                "status": "passed",
                "git_sha": "1" * 40,
            }
        ),
        encoding="utf-8",
    )
    return output


def _public_manifests() -> tuple[
    dict[str, object],
    dict[str, object],
    tuple[object, ...],
]:
    tool_id = "a" * 64
    return (
        {
            "format": "weave-jacquard-tool-manifest-v2",
            "tool_count": 1,
            "tool_names": ["alpha"],
            "tools": [{"name": "alpha", "input_schema": {"type": "object"}}],
            "tool_manifest_id": tool_id,
        },
        {
            "format": "weave-jacquard-application-v2",
            "capabilities": [],
            "configuration_variables": [],
            "tool_count": 1,
            "tool_manifest_id": tool_id,
            "application_id": "b" * 64,
        },
        (
            {
                "name": "base",
                "module": "example.base",
                "depends_on": [],
            },
        ),
    )


def test_release_qualification_wrapper_parses() -> None:
    completed = subprocess.run(
        ["bash", "-n", str(ROOT / "scripts" / "qualify-release.sh")],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_release_manifest_evidence_is_canonical_and_indexed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = _qualified_output(tmp_path)
    monkeypatch.setattr(release_manifests, "_public_manifests", _public_manifests)

    index = release_manifests.retain_public_manifests(output)

    assert index["format"] == release_manifests.MANIFEST_INDEX_FORMAT
    assert index["qualification_git_sha"] == "1" * 40
    assert index["tool_manifest_id"] == "a" * 64
    assert index["application_id"] == "b" * 64
    assert [entry["kind"] for entry in index["manifests"]] == [
        "tool",
        "application",
        "capability",
    ]
    for entry in index["manifests"]:
        retained = output / entry["path"]
        assert retained.is_file()
        assert retained.stat().st_size == entry["bytes"]
        assert len(entry["sha256"]) == 64
        payload = retained.read_bytes()
        assert payload.endswith(b"\n")
        assert b": " not in payload
    capability = json.loads(
        (output / "manifests" / "capability-manifest.json").read_text(encoding="utf-8")
    )
    assert capability["format"] == "weave-jacquard-capability-manifest-v1"
    assert capability["capabilities"][0]["name"] == "base"


def test_release_manifest_evidence_rejects_identity_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = _qualified_output(tmp_path)
    tool, application, capabilities = _public_manifests()
    application["tool_manifest_id"] = "c" * 64
    monkeypatch.setattr(
        release_manifests,
        "_public_manifests",
        lambda: (tool, application, capabilities),
    )

    with pytest.raises(
        release_manifests.ManifestEvidenceError,
        match="does not reference",
    ):
        release_manifests.retain_public_manifests(output)


def test_release_manifest_evidence_requires_passed_qualification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = _qualified_output(tmp_path)
    completion = output / "qualification-complete.json"
    document = json.loads(completion.read_text(encoding="utf-8"))
    document["status"] = "failed"
    completion.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(release_manifests, "_public_manifests", _public_manifests)

    with pytest.raises(
        release_manifests.ManifestEvidenceError,
        match="passed qualification",
    ):
        release_manifests.retain_public_manifests(output)


def test_release_qualification_regenerates_checksums_after_manifests() -> None:
    wrapper = (ROOT / "scripts" / "qualify-release.sh").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "native-e2e.yml").read_text(encoding="utf-8")

    qualify = wrapper.index('scripts/qualify.sh"')
    retain = wrapper.index('scripts/retain-public-manifests.py"')
    checksums = wrapper.index('scripts/qualification.py" checksums')
    assert qualify < retain < checksums
    assert "bash scripts/qualify-release.sh native" in workflow
