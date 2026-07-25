from __future__ import annotations

import json
import subprocess
from pathlib import Path

from weave_frontend.compiler_bridge import CompilerBridge
from weave_frontend.sexpr_service import SExpressionWorkspace


PROGRAM_V1 = """(program
  (name \"demo\")
  (version \"0.1\")
  (entry main
    (params)
    (returns i32)
    (do (return (const_i32 42)))))
"""

PROGRAM_V2 = PROGRAM_V1.replace('(version "0.1")', '(version "0.2")')


def _fake_compiler(path: Path) -> Path:
    path.write_text(
        """#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 6 or sys.argv[1] != "build":
        return 2
    source = Path(sys.argv[2])
    try:
        output_index = sys.argv.index("-o")
        manifest_index = sys.argv.index("--manifest-json")
    except ValueError:
        return 2
    output = Path(sys.argv[output_index + 1])
    manifest = Path(sys.argv[manifest_index + 1])
    text = source.read_text(encoding="utf-8")
    if "force-build-failure" in text:
        print("requested fake compiler failure", file=sys.stderr)
        return 7
    output.write_text("#!/bin/sh\\nexit 42\\n", encoding="utf-8")
    os.chmod(output, 0o755)
    manifest.write_text(
        json.dumps(
            {
                "format": "weavec-build-manifest-v1",
                "status": "succeeded",
                "source": str(source),
                "output": str(output),
            },
            indent=2,
        )
        + "\\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def test_build_is_pinned_to_requested_revision_and_reused(tmp_path: Path) -> None:
    compiler = _fake_compiler(tmp_path / "weavec")
    database = tmp_path / "weave.db"
    build_root = tmp_path / "builds"

    with SExpressionWorkspace(database, weavec_binary=compiler) as workspace:
        workspace.initialize("demo")
        first = workspace.import_program("demo", "main", "main.weave", PROGRAM_V1)
        first_revision = str(first["revision_id"])
        workspace.import_program(
            "demo",
            "main",
            "main.weave",
            PROGRAM_V2,
            replace=True,
        )
        current_revision = workspace.branch_head("demo", "main")
        assert current_revision != first_revision

        bridge = CompilerBridge(
            workspace,
            compiler=compiler,
            build_root=build_root,
        )
        result = bridge.build(
            "demo",
            "main.weave",
            revision_id=first_revision,
        )
        cached = bridge.build(
            "demo",
            "main.weave",
            revision_id=first_revision,
        )

    assert result["status"] == "succeeded"
    assert result["revision_id"] == first_revision
    assert result["cached"] is False
    assert cached["build_id"] == result["build_id"]
    assert cached["cached"] is True

    source = Path(result["artifact_paths"]["source"]).read_text(encoding="utf-8")
    node_map = json.loads(
        Path(result["artifact_paths"]["node_map"]).read_text(encoding="utf-8")
    )
    executable = Path(result["artifact_paths"]["executable"])

    assert '(version "0.1")' in source
    assert '(version "0.2")' not in source
    assert "@n_" not in source
    assert node_map["revision_id"] == first_revision
    assert subprocess.run([str(executable)], check=False).returncode == 42


def test_failed_build_keeps_database_revision_unchanged(tmp_path: Path) -> None:
    compiler = _fake_compiler(tmp_path / "weavec")
    database = tmp_path / "weave.db"

    failing_source = PROGRAM_V1.replace(
        '(name "demo")',
        '(name "force-build-failure")',
    )
    with SExpressionWorkspace(database, weavec_binary=compiler) as workspace:
        workspace.initialize("demo")
        imported = workspace.import_program(
            "demo",
            "main",
            "main.weave",
            failing_source,
        )
        revision = str(imported["revision_id"])
        bridge = CompilerBridge(
            workspace,
            compiler=compiler,
            build_root=tmp_path / "builds",
        )
        result = bridge.build("demo", "main.weave")
        head_after = workspace.branch_head("demo", "main")

    assert result["status"] == "failed"
    assert result["returncode"] == 7
    assert result["revision_id"] == revision
    assert result["artifact_paths"]["executable"] is None
    assert head_after == revision
    diagnostics = json.loads(
        Path(result["artifact_paths"]["diagnostics"]).read_text(encoding="utf-8")
    )
    assert "requested fake compiler failure" in diagnostics["stderr"]
