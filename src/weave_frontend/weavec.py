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

    def _active_binary(self) -> Path | None:
        """Return a currently executable compiler, re-resolving stale paths."""

        if self.binary is not None and self.binary.is_file() and os.access(self.binary, os.X_OK):
            return self.binary
        self.binary = self._resolve_binary(None)
        return self.binary

    def validate(self, source: str) -> dict[str, Any]:
        """Validate one source document through the canonical frontend."""

        return self.validate_sources([("program.weave", source)])

    def validate_sources(self, sources: list[tuple[str, str]]) -> dict[str, Any]:
        """Validate an explicit ordered source set through ``weavec --frontend``."""

        if not sources:
            raise ValueError("at least one source document is required")
        if any(
            not isinstance(document, str)
            or not document
            or not isinstance(source, str)
            for document, source in sources
        ):
            raise ValueError("source documents require non-empty names and string content")

        documents = [document for document, _ in sources]
        binary = self._active_binary()
        if binary is None:
            return {
                "available": False,
                "valid": None,
                "returncode": None,
                "diagnostic": (
                    "weavec binary not found. Set WEAVEC_BIN, install weavec on PATH, "
                    "or provide a weavec source root containing build/weavec."
                ),
                "documents": documents,
            }

        with tempfile.TemporaryDirectory(prefix="weave-validate-") as temporary:
            temp = Path(temporary)
            wir_path = temp / "program.wir"
            source_paths: list[Path] = []
            for index, (document, source) in enumerate(sources):
                basename = self._safe_basename(document)
                source_path = temp / f"{index:03d}-{basename}"
                source_path.write_text(source, encoding="utf-8")
                source_paths.append(source_path)

            command = [
                str(binary),
                "--frontend",
                str(wir_path),
                *(str(path) for path in source_paths),
            ]
            try:
                completed = subprocess.run(
                    command,
                    text=True,
                    capture_output=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                stdout = self._text(exc.stdout)
                stderr = self._text(exc.stderr)
                diagnostic = f"weavec validation timed out after {exc.timeout} seconds"
                return {
                    "available": True,
                    "valid": False,
                    "returncode": None,
                    "stdout": stdout,
                    "stderr": stderr,
                    "diagnostic": diagnostic,
                    "timed_out": True,
                    "documents": documents,
                }
            except OSError as exc:
                return {
                    "available": False,
                    "valid": None,
                    "returncode": None,
                    "stdout": "",
                    "stderr": f"weavec validation could not start: {exc}\n",
                    "diagnostic": f"weavec validation could not start: {exc}",
                    "timed_out": False,
                    "documents": documents,
                }

            return {
                "available": True,
                "valid": completed.returncode == 0,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "wir": wir_path.read_text(encoding="utf-8") if wir_path.exists() else None,
                "timed_out": False,
                "documents": documents,
            }

    @staticmethod
    def _text(value: str | bytes | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode(errors="replace")
        return value

    @staticmethod
    def _safe_basename(document: str) -> str:
        basename = document.replace("\\", "/").rsplit("/", 1)[-1]
        safe = "".join(
            character
            if character.isalnum() or character in {".", "_", "-"}
            else "_"
            for character in basename
        )
        if not safe:
            safe = "source.weave"
        if not safe.endswith(".weave"):
            safe += ".weave"
        return safe
