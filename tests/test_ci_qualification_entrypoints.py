from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]


def _workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_python_ci_runs_portable_qualification() -> None:
    workflow = _workflow("ci.yml")

    assert "runs-on: self-hosted" in workflow
    assert 'qualification_dir="$GITHUB_WORKSPACE/qualification-evidence"' in workflow
    assert 'virtualenv_dir="$GITHUB_WORKSPACE/.venv-ci"' in workflow
    assert '"$SYSTEM_PYTHON_BIN" -m venv "$VIRTUALENV_DIR"' in workflow
    assert "BubblewrapSandbox" in workflow
    assert '"$PYTHON_BIN" -m compileall -q src tests scripts/qualification.py' in workflow
    assert '"$PYTHON_BIN" -m ruff check .' in workflow
    assert '"$PYTHON_BIN" -m pytest' in workflow
    assert '-m "not real_e2e"' in workflow
    assert "--cov=weave_frontend" in workflow
    assert 'bash scripts/qualify.sh python "$QUALIFICATION_DIR"' not in workflow
    assert "if: always()" in workflow
    assert "if-no-files-found: warn" in workflow


def test_native_ci_delegates_to_unified_qualification() -> None:
    workflow = _workflow("native-e2e.yml")

    assert 'bash scripts/qualify.sh native "$QUALIFICATION_DIR"' in workflow
    assert "python -m pytest" not in workflow
    assert "qualification-summary.json" not in workflow
    assert "bubblewrap clang file llvm" in workflow
    # Job-level env: can't reference the runner context, so this is set via
    # GITHUB_ENV in a step instead of a literal `COMPILER_STAGE: ...` env line.
    assert 'COMPILER_STAGE=${{ runner.temp }}/jacquard-weavec-release' in workflow
    assert '> "$COMPILER_STAGE/release-metadata.json"' in workflow
    assert "if-no-files-found: error" in workflow
