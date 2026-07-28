from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]


def _workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_python_ci_delegates_to_unified_qualification() -> None:
    workflow = _workflow("ci.yml")

    assert 'bash scripts/qualify.sh python "$QUALIFICATION_DIR"' in workflow
    assert "python -m compileall" not in workflow
    assert "ruff check" not in workflow
    assert "pytest -q" not in workflow
    assert "qualification-traces.json" not in workflow
    assert "if-no-files-found: error" in workflow


def test_native_ci_delegates_to_unified_qualification() -> None:
    workflow = _workflow("native-e2e.yml")

    assert 'bash scripts/qualify.sh native "$QUALIFICATION_DIR"' in workflow
    assert "python -m pytest" not in workflow
    assert "qualification-summary.json" not in workflow
    assert "bubblewrap clang file llvm" in workflow
    assert "if-no-files-found: error" in workflow
