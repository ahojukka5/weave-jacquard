from __future__ import annotations

import json
from pathlib import Path

from weave_frontend.compiler_bridge import CompilerBridge
from weave_frontend.sexpr_service import SExpressionWorkspace


PROGRAM = """(program
  (name \"demo\")
  (version \"0.1\")
  (entry main
    (params)
    (returns i32)
    (do (return (const_i32 42)))))
"""


def test_compiler_launch_failure_is_published_as_diagnostics(tmp_path: Path) -> None:
    compiler = tmp_path / "weavec"
    compiler.write_text("#!/definitely/missing/interpreter\n", encoding="utf-8")
    compiler.chmod(0o755)

    with SExpressionWorkspace(tmp_path / "weave.db", weavec_binary=compiler) as workspace:
        workspace.initialize("demo")
        imported = workspace.import_program(
            "demo",
            "main",
            "main.weave",
            PROGRAM,
        )
        revision = str(imported["revision_id"])
        bridge = CompilerBridge(
            workspace,
            compiler=compiler,
            build_root=tmp_path / "builds",
        )
        result = bridge.build("demo", "main.weave")

    assert result["status"] == "failed"
    assert result["returncode"] is None
    assert result["revision_id"] == revision
    assert result["artifact_paths"]["executable"] is None

    diagnostics = json.loads(
        Path(result["artifact_paths"]["diagnostics"]).read_text(encoding="utf-8")
    )
    assert diagnostics["returncode"] is None
    assert diagnostics["timed_out"] is False
    assert "could not start" in diagnostics["stderr"]
