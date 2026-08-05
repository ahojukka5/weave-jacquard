from __future__ import annotations

from pathlib import Path

from weave_frontend.sandbox import BubblewrapSandbox


def _executable(path: Path) -> Path:
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_missing_prlimit_reports_unavailable(tmp_path: Path) -> None:
    sandbox = BubblewrapSandbox(
        _executable(tmp_path / "bwrap"),
        prlimit=tmp_path / "missing-prlimit",
    )

    capabilities = sandbox.capabilities()

    assert capabilities["available"] is False
    assert capabilities["probe_error"] == ("configured prlimit path is not an executable file")
    assert capabilities["resource_limits"]["process_count"] is True
    assert capabilities["resource_limits"]["aggregate_memory"] is False
    assert capabilities["policy"]["process_creation"] == "deny"
    assert capabilities["policy"]["max_processes"] == 1
