"""Production compiler bridge with aggregate artifact quota admission."""

from __future__ import annotations

from pathlib import Path
from typing import Any

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


def install_quota_aware_compiler_bridge(bridge: Any) -> CompilerBridge:
    """Upgrade the existing cached production bridge without rebuilding dependents."""

    if isinstance(bridge, CompilerBridge):
        return bridge
    if type(bridge) is not _CompilerBridge:
        raise RuntimeError("production compiler bridge has an unsupported type")
    bridge.__class__ = CompilerBridge
    return bridge


__all__ = ["CompilerBridge", "install_quota_aware_compiler_bridge"]
