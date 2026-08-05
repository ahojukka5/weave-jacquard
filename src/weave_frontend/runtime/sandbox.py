"""Production sandbox construction from immutable runtime configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..sandbox import BubblewrapSandbox
from .config import RuntimeConfig


class RuntimeBubblewrapSandbox(BubblewrapSandbox):
    """Bubblewrap backend whose executable selection cannot reread the environment."""

    def __init__(
        self,
        executable: str | Path | None,
        *,
        prlimit: str | Path | None,
    ) -> None:
        self.executable = self._resolved_optional_path(executable)
        self.prlimit = self._resolved_optional_path(prlimit)
        self._capabilities: dict[str, Any] | None = None

    @classmethod
    def from_config(cls, config: RuntimeConfig) -> RuntimeBubblewrapSandbox:
        return cls(
            config.bubblewrap_binary,
            prlimit=config.prlimit_binary,
        )

    @staticmethod
    def _resolved_optional_path(value: str | Path | None) -> Path | None:
        return None if value is None else Path(value).expanduser().resolve()


__all__ = ["RuntimeBubblewrapSandbox"]
