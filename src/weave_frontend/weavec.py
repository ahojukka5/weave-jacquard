"""Adapter to the authoritative ``weavec`` surface frontend."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .bounded_process import run_bounded_process
from .compiler_io import CompilerFileTooLarge, read_bounded_text
from .compiler_limits import MAX_COMPILER_OUTPUT_BYTES, MAX_WIR_BYTES


class WeavecValidator:
    """Validate surface Weave with the canonical user-facing compiler."""

    def __init__(
        self,
        binary: str | Path | None = None,
        source_root: str | Path | None = None,
        *,
        timeout_seconds: int = 30,
        max_output_bytes: int = MAX_COMPILER_OUTPUT_BYTES,
        max_wir_bytes: int = MAX_WIR_BYTES,
        environment_fallback: bool = True,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        for name, value in (
            ("max_output_bytes", max_output_bytes),
            ("max_wir_bytes", max_wir_bytes),
        ):
            if isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if not isinstance(environment_fallback, bool):
            raise TypeError("environment_fallback must be boolean")
        self.source_root = Path(source_root).resolve() if source_root else None
        self.environment_fallback = environment_fallback
        self.binary = self._resolve_binary(binary)
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.max_wir_bytes = max_wir_bytes

    def _resolve_binary(self, binary: str | Path | None) -> Path | None:
        configured = binary
        if configured is None and self.environment_fallback:
            configured = os.environ.get("WEAVEC_BIN")
        candidates: list[Path] = []
        if configured:
            candidates.append(Path(configured).expanduser())

        if self.environment_fallback:
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

        if self.binary is not None and self.binary.is_file() and os.access(
            self.binary,
            os.X_OK,
        ):
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
                completed = run_bounded_process(
                    command,
                    timeout_seconds=self.timeout_seconds,
                    max_output_bytes=self.max_output_bytes,
                )
            except OSError as exc:
                return {
                    "available": False,
                    "valid": None,
                    "returncode": None,
                    "stdout": "",
                    "stderr": f"weavec validation could not start: {exc}\n",
                    "diagnostic": f"weavec validation could not start: {exc}",
                    "timed_out": False,
                    "output_limited": False,
                    "documents": documents,
                }

            if completed.timed_out:
                return {
                    "available": True,
                    "valid": False,
                    "returncode": None,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                    "diagnostic": (
                        f"weavec validation timed out after {self.timeout_seconds} seconds"
                    ),
                    "timed_out": True,
                    "output_limited": False,
                    "compiler_output_limit_bytes": self.max_output_bytes,
                    "documents": documents,
                }
            if completed.output_limited:
                return {
                    "available": True,
                    "valid": False,
                    "returncode": None,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                    "diagnostic": (
                        "weavec validation exceeded the combined stdout/stderr limit "
                        f"of {self.max_output_bytes} bytes"
                    ),
                    "timed_out": False,
                    "output_limited": True,
                    "compiler_output_limit_bytes": self.max_output_bytes,
                    "documents": documents,
                }

            wir: str | None = None
            wir_too_large = False
            wir_error: str | None = None
            if wir_path.is_file():
                try:
                    wir = read_bounded_text(wir_path, max_bytes=self.max_wir_bytes)
                except CompilerFileTooLarge as exc:
                    wir_too_large = True
                    wir_error = str(exc)
                except (OSError, UnicodeError) as exc:
                    wir_error = f"cannot read generated WIR: {exc}"

            valid = completed.returncode == 0 and wir_error is None
            diagnostic = wir_error
            if completed.returncode == 0 and not wir_path.is_file():
                valid = False
                diagnostic = "weavec validation succeeded without writing WIR"

            return {
                "available": True,
                "valid": valid,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "wir": wir,
                "timed_out": False,
                "output_limited": False,
                "compiler_output_limit_bytes": self.max_output_bytes,
                "wir_limit_bytes": self.max_wir_bytes,
                "wir_too_large": wir_too_large,
                "diagnostic": diagnostic,
                "documents": documents,
            }

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
