#!/usr/bin/env python3
"""Rename the active weavec2 integration to canonical weavec interfaces."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD_MODULE = ROOT / "src/weave_frontend/weavec2.py"
NEW_MODULE = ROOT / "src/weave_frontend/weavec.py"

if not OLD_MODULE.exists():
    raise SystemExit(f"missing source module: {OLD_MODULE.relative_to(ROOT)}")
if NEW_MODULE.exists():
    raise SystemExit(f"target module already exists: {NEW_MODULE.relative_to(ROOT)}")
OLD_MODULE.rename(NEW_MODULE)

replacements = (
    ("Weavec2Validator", "WeavecValidator"),
    ("weavec2_source_root", "weavec_source_root"),
    ("weavec2_binary", "weavec_binary"),
    ("WEAVEC2_BIN", "WEAVEC_BIN"),
    ("weavec2.py", "weavec.py"),
    (".weavec2", ".weavec"),
    ("weavec2", "weavec"),
    ("Weavec2", "Weavec"),
)

raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
for item in raw.split(b"\0"):
    if not item:
        continue
    relative = Path(item.decode())
    path = ROOT / relative
    if relative == Path(".github/workflows/ci.yml") or not path.is_file():
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    original = text
    for old, new in replacements:
        text = text.replace(old, new)
    if text != original:
        path.write_text(text, encoding="utf-8")

NEW_MODULE.write_text(
    '''"""Adapter to the authoritative ``weavec`` surface frontend."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class WeavecValidator:
    """Validate surface Weave with the canonical user-facing compiler."""

    def __init__(
        self,
        binary: str | Path | None = None,
        source_root: str | Path | None = None,
        *,
        timeout_seconds: int = 30,
    ) -> None:
        self.source_root = Path(source_root).resolve() if source_root else None
        self.binary = self._resolve_binary(binary)
        self.timeout_seconds = timeout_seconds

    def _resolve_binary(self, binary: str | Path | None) -> Path | None:
        configured = binary or os.environ.get("WEAVEC_BIN")
        candidates: list[Path] = []
        if configured:
            candidates.append(Path(configured).expanduser())

        installed = shutil.which("weavec")
        if installed:
            candidates.append(Path(installed))

        if self.source_root is not None:
            candidates.append(self.source_root / "build" / "weavec")

        candidates.extend(
            [
                Path.cwd() / "weavec" / "build" / "weavec",
                Path.cwd().parent / "weavec" / "build" / "weavec",
            ]
        )
        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate.resolve()
        return None

    def validate(self, source: str) -> dict[str, Any]:
        if self.binary is None:
            return {
                "available": False,
                "valid": None,
                "diagnostic": (
                    "weavec binary not found. Set WEAVEC_BIN, install weavec on PATH, "
                    "or provide a weavec source root containing build/weavec."
                ),
            }

        with tempfile.TemporaryDirectory(prefix="weave-validate-") as temporary:
            temp = Path(temporary)
            source_path = temp / "program.weave"
            wir_path = temp / "program.wir"
            source_path.write_text(source, encoding="utf-8")
            try:
                completed = subprocess.run(
                    [str(self.binary), "--frontend", str(wir_path), str(source_path)],
                    text=True,
                    capture_output=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                return {
                    "available": True,
                    "valid": False,
                    "returncode": None,
                    "diagnostic": (
                        f"weavec validation timed out after {exc.timeout} seconds"
                    ),
                }

            return {
                "available": True,
                "valid": completed.returncode == 0,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "wir": wir_path.read_text(encoding="utf-8") if wir_path.exists() else None,
            }
''',
    encoding="utf-8",
)

# The old path and active names must disappear completely from the current tree.
remaining: list[str] = []
for path in ROOT.rglob("*"):
    if not path.is_file() or ".git" in path.parts:
        continue
    if path == ROOT / ".github/workflows/ci.yml":
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    if "weavec2" in text or "WEAVEC2" in text or "Weavec2" in text:
        remaining.append(str(path.relative_to(ROOT)))
if remaining:
    raise SystemExit("legacy active names remain: " + ", ".join(sorted(remaining)))
if OLD_MODULE.exists():
    raise SystemExit("legacy module path still exists")

Path(__file__).unlink()
