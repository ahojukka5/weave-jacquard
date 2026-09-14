from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]


def _architecture_section(architecture: str, heading: str) -> str:
    marker = f"## {heading}"
    start = architecture.index(marker)
    remainder = architecture[start + len(marker) :]
    next_heading = remainder.find("\n## ")
    if next_heading == -1:
        return remainder
    return remainder[:next_heading]


def test_readme_uses_generated_manifest_as_tool_inventory() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "generated manifest is the authoritative tool inventory" in readme
    assert "projects, branches, checkout, and history" not in readme
    assert "tested-merge attestations" in readme
    assert "agent checkpoints" in readme
    assert "DATABASE_BUSY" in readme


def test_architecture_does_not_list_completed_capabilities_as_omissions() -> None:
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    remaining = _architecture_section(architecture, "15.")

    assert "affected-test selection and preview consequences" not in architecture
    assert "sandboxed program execution tools" not in architecture
    assert (
        "database integrity, backup, and artifact-retention operations"
        not in architecture
    )
    assert "remain operator capabilities to implement" not in architecture
    assert "highest-value remaining work" not in remaining
    assert "Runtime service-graph completion" not in remaining
    assert "Database and artifact integrity" not in remaining
    assert "Retention and storage operations" not in remaining
    assert "live remaining-work inventory" in remaining
    assert "already shipped" in remaining


def test_architecture_describes_split_local_and_github_qualification() -> None:
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    qualification = _architecture_section(architecture, "13.")

    assert "GitHub workflows only acquire prerequisites, invoke the same runner" not in (
        architecture
    )
    assert "scripts/qualify.sh python" in qualification
    assert 'pytest -m "not real_e2e"' in qualification
    assert "qualify-release.sh native" in qualification
    assert "do not all invoke that runner" in qualification


def test_architecture_distinguishes_preview_from_retained_candidate_evidence() -> None:
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")

    assert "A structural preview is in memory" in architecture
    assert "candidate build and test operations may retain" in architecture
    assert "creates no revision, executable, build manifest" not in architecture
