"""Production compiler bridge with aggregate artifact quota admission."""

from __future__ import annotations

from pathlib import Path

from .artifact_quota import artifact_quota_admission
from .compiler_bridge import CompilerBridge as _CompilerBridge


class CompilerBridge(_CompilerBridge):
    """Publish committed builds only after aggregate quota admission."""

    def _publish_directory(self, temporary: Path, final: Path) -> None:
        with artifact_quota_admission(
            self,
            family="committed_builds",
            temporary=temporary,
            final=final,
        ):
            super()._publish_directory(temporary, final)


__all__ = ["CompilerBridge"]
