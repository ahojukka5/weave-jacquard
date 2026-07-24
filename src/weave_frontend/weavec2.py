"""Adapter to the authoritative weavec2 surface frontend."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any


class Weavec2Validator:
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
        candidates: list[Path] = []
        configured = binary or os.environ.get("WEAVEC2_BIN")
        if configured:
            candidates.append(Path(configured))
        if self.source_root is not None:
            candidates.append(self.source_root / "build" / "weavec2")
        candidates.extend(
            [
                Path.cwd() / "weavec2" / "build" / "weavec2",
                Path.cwd().parent / "weavec2" / "build" / "weavec2",
            ]
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()
        return None

    def validate(self, source: str) -> dict[str, Any]:
        if self.binary is None:
            return {
                "available": False,
                "valid": None,
                "diagnostic": (
                    "weavec2 binary not found. Set WEAVEC2_BIN or place weavec2 in a "
                    "sibling checkout with build/weavec2 available."
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
                    "diagnostic": f"weavec2 validation timed out after {exc.timeout} seconds",
                }
            return {
                "available": True,
                "valid": completed.returncode == 0,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "wir": wir_path.read_text(encoding="utf-8") if wir_path.exists() else None,
            }
