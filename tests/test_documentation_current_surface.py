from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_readme_uses_generated_manifest_as_tool_inventory() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "generated manifest is the authoritative tool inventory" in readme
    assert "projects, branches, checkout, and history" not in readme
    assert "tested-merge attestations" in readme
    assert "agent checkpoints" in readme
    assert "DATABASE_BUSY" in readme


def test_architecture_does_not_list_completed_capabilities_as_omissions() -> None:
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")

    assert "affected-test selection and preview consequences" not in architecture
    assert "sandboxed program execution tools" not in architecture
    assert (
        "database integrity, backup, and artifact-retention operations"
        not in architecture
    )
    assert "Runtime service-graph completion" in architecture
    assert "Database and artifact integrity" in architecture
    assert "Retention and storage operations" in architecture


def test_architecture_distinguishes_preview_from_retained_candidate_evidence() -> None:
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")

    assert "A structural preview is in memory" in architecture
    assert "candidate build and test operations may retain" in architecture
    assert "creates no revision, executable, build manifest" not in architecture
