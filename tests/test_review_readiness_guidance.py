from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_top_level_guidance_requires_issue_closure_and_green_ci() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

    for document in (agents, contributing):
        assert "Closes #<issue>" in document
        assert "exact final head" in document
        assert "keep" in document.lower()
        assert "draft" in document.lower()
        assert "red" in document.lower()
        assert "unfinished" in document.lower()
    assert "docs/agent-development-rules.md" in agents
    assert "docs/contributor-development-guide.md" in contributing
