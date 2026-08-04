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


def test_native_ci_delegates_to_release_qualification() -> None:
    workflow = _workflow("native-e2e.yml")
    wrapper = (ROOT / "scripts" / "qualify-release.sh").read_text(
        encoding="utf-8"
    )

    assert 'bash scripts/qualify-release.sh native "$QUALIFICATION_DIR"' in workflow
    assert 'scripts/qualify.sh" "$mode" "$requested_out"' in wrapper
    assert 'scripts/retain-public-manifests.py" "$final_out"' in wrapper
    assert 'scripts/qualification.py" checksums "$final_out"' in wrapper
    assert "python -m pytest" not in workflow
    assert "qualification-summary.json" not in workflow
    assert "bubblewrap clang file llvm" in workflow
    # Job-level env cannot reference runner.temp, so scratch roots are exported
    # through GITHUB_ENV before the exact provider is fetched and built.
    assert 'COMPILER_STAGE=${{ runner.temp }}/jacquard-weavec-provider' in workflow
    assert "WEAVEC_REPOSITORY: ahojukka5/weavec" in workflow
    assert "WEAVEC_COMMIT: f5c1196b3a75c0b2721b3bd753edbcc8d1388244" in workflow
    assert 'git -C "$source_root" fetch --depth=1 origin "$WEAVEC_COMMIT"' in workflow
    assert '"$compiler_path" capabilities --json' in workflow
    assert 'provider-metadata.json' in workflow
    assert 'capabilities.json' in workflow
    assert "if: always()" in workflow
    assert "if-no-files-found: error" in workflow
