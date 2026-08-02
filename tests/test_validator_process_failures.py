from __future__ import annotations

from pathlib import Path

from weave_frontend.weavec import WeavecValidator

PROGRAM = '(program (name "demo") (version "0.1"))\n'


def test_validator_launch_failure_is_structured(tmp_path: Path) -> None:
    compiler = tmp_path / "weavec"
    compiler.write_text("#!/definitely/missing/interpreter\n", encoding="utf-8")
    compiler.chmod(0o755)

    result = WeavecValidator(compiler).validate(PROGRAM)

    assert result["available"] is False
    assert result["valid"] is None
    assert result["returncode"] is None
    assert result["timed_out"] is False
    assert result["documents"] == ["program.weave"]
    assert "could not start" in result["diagnostic"]
    assert "could not start" in result["stderr"]


def test_validator_timeout_preserves_partial_output(tmp_path: Path) -> None:
    compiler = tmp_path / "weavec"
    compiler.write_text(
        "#!/bin/sh\n"
        "printf 'partial stdout'\n"
        "printf 'partial stderr' >&2\n"
        "while :; do :; done\n",
        encoding="utf-8",
    )
    compiler.chmod(0o755)
    validator = WeavecValidator(compiler, timeout_seconds=0.05)

    for _ in range(25):
        result = validator.validate(PROGRAM)

        assert result["available"] is True
        assert result["valid"] is False
        assert result["returncode"] is None
        assert result["timed_out"] is True
        assert result["documents"] == ["program.weave"]
        assert "timed out" in result["diagnostic"]
        assert result["stdout"] == "partial stdout"
        assert result["stderr"] == "partial stderr"
