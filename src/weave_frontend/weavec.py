"""Adapter to the authoritative ``weavec`` surface frontend."""

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
