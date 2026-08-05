from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_qualification_enforces_repository_wide_ruff_gate() -> None:
    qualification = (ROOT / "scripts" / "qualify.sh").read_text(encoding="utf-8")
    configuration = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '"${ruff_cmd[@]}" check .' in qualification
    assert "[tool.ruff.lint]" in configuration
    assert 'select = ["E", "F", "I", "UP", "B", "SIM"]' in configuration
    assert "per-file-ignores" not in configuration
