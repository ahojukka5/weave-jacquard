"""Final bounded filesystem admission for stored-build discovery."""

from __future__ import annotations

from pathlib import Path

from .build_discovery import BuildDiscoveryService as _BuildDiscoveryService
from .errors import ValidationError

MAX_BUILD_CATALOG_ENTRIES = 65_536


class BuildDiscoveryService(_BuildDiscoveryService):
    """Discover verified builds without unbounded root enumeration."""

    def _candidate_build_ids(self) -> list[str]:
        entries: list[Path] = []
        try:
            for index, entry in enumerate(self.bridge.build_root.iterdir()):
                if index >= MAX_BUILD_CATALOG_ENTRIES:
                    raise ValidationError(
                        "BUILD_CATALOG_LIMIT_EXCEEDED",
                        "stored build root exceeds the bounded catalog entry limit "
                        f"{MAX_BUILD_CATALOG_ENTRIES}",
                    )
                entries.append(entry)
        except ValidationError:
            raise
        except OSError as exc:
            raise ValidationError(
                "BUILD_CATALOG_UNAVAILABLE",
                "cannot enumerate stored build root",
            ) from exc

        result: list[str] = []
        for entry in entries:
            try:
                if not self._valid_build_id(entry.name) or entry.is_symlink():
                    continue
                manifest = entry / "manifest.json"
                is_directory = entry.is_dir()
                is_manifest = manifest.is_file() and not manifest.is_symlink()
            except OSError:
                continue
            if is_directory and is_manifest:
                result.append(entry.name)
        return sorted(result)


__all__ = ["MAX_BUILD_CATALOG_ENTRIES", "BuildDiscoveryService"]
