"""Typed immutable startup configuration for the Jacquard runtime."""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import ClassVar

from ..artifacts.quota import parse_artifact_quota

PUBLIC_CONFIGURATION_VARIABLES: tuple[str, ...] = (
    "WEAVEC_BIN",
    "WEAVEC_SOURCE_ROOT",
    "WEAVE_ARTIFACT_MAX_BYTES",
    "WEAVE_BUILD_ROOT",
    "WEAVE_BWRAP",
    "WEAVE_DATABASE_BACKUP_ROOT",
    "WEAVE_DB_PATH",
    "WEAVE_MERGE_ATTESTATION_ROOT",
    "WEAVE_MERGE_BUILD_ROOT",
    "WEAVE_MERGE_TEST_RUN_ROOT",
    "WEAVE_TEST_BATCH_ROOT",
    "WEAVE_TEST_RUN_ROOT",
)


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """One process-stable typed snapshot of supported environment configuration."""

    configuration_variables: ClassVar[tuple[str, ...]] = PUBLIC_CONFIGURATION_VARIABLES

    database_path: Path
    weavec_binary: str | None
    weavec_source_root: Path | None
    artifact_max_bytes: int | None
    build_root: Path
    bubblewrap_binary: str | None
    prlimit_binary: str | None
    database_backup_root: Path
    merge_attestation_root: Path
    merge_build_root: Path
    merge_test_run_root: Path
    test_batch_root: Path
    test_run_root: Path
    _configured_values: tuple[tuple[str, str], ...]

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> RuntimeConfig:
        """Capture and validate supported variables without retaining a mutable mapping."""

        values = {
            name: cls._optional_value(environ, name) for name in PUBLIC_CONFIGURATION_VARIABLES
        }
        configured = tuple(
            (name, value)
            for name in PUBLIC_CONFIGURATION_VARIABLES
            if (value := values[name]) is not None
        )

        database_path = cls._resolved_path(values["WEAVE_DB_PATH"] or "weave.db")
        database_parent = database_path.parent
        source_root = cls._optional_path(values["WEAVEC_SOURCE_ROOT"])
        build_root = cls._path_or_default(
            values["WEAVE_BUILD_ROOT"],
            database_parent / ".weave-build",
        )
        test_run_root = cls._path_or_default(
            values["WEAVE_TEST_RUN_ROOT"],
            database_parent / ".weave-test-runs",
        )

        explicit_weavec = values["WEAVEC_BIN"]
        weavec_binary = cls._optional_resolved_string(explicit_weavec)
        if weavec_binary is None:
            weavec_binary = cls._discover_weavec(source_root)
        explicit_bwrap = values["WEAVE_BWRAP"]
        bubblewrap_binary = cls._optional_resolved_string(explicit_bwrap)
        if bubblewrap_binary is None:
            bubblewrap_binary = cls._optional_resolved_string(shutil.which("bwrap"))

        return cls(
            database_path=database_path,
            weavec_binary=weavec_binary,
            weavec_source_root=source_root,
            artifact_max_bytes=parse_artifact_quota(values["WEAVE_ARTIFACT_MAX_BYTES"]),
            build_root=build_root,
            bubblewrap_binary=bubblewrap_binary,
            prlimit_binary=cls._optional_resolved_string(shutil.which("prlimit")),
            database_backup_root=cls._path_or_default(
                values["WEAVE_DATABASE_BACKUP_ROOT"],
                database_parent / ".weave-database-backups",
            ),
            merge_attestation_root=cls._path_or_default(
                values["WEAVE_MERGE_ATTESTATION_ROOT"],
                database_parent / ".weave-merge-attestations",
            ),
            merge_build_root=cls._path_or_default(
                values["WEAVE_MERGE_BUILD_ROOT"],
                build_root / "merge-candidates",
            ),
            merge_test_run_root=cls._path_or_default(
                values["WEAVE_MERGE_TEST_RUN_ROOT"],
                database_parent / ".weave-merge-test-runs",
            ),
            test_batch_root=cls._path_or_default(
                values["WEAVE_TEST_BATCH_ROOT"],
                test_run_root / "batches",
            ),
            test_run_root=test_run_root,
            _configured_values=configured,
        )

    @property
    def configured_environment(self) -> Mapping[str, str]:
        """Return an immutable mapping of explicitly non-empty configured values."""

        return MappingProxyType(dict(self._configured_values))

    @property
    def configured_variables(self) -> tuple[str, ...]:
        """Return explicitly configured variable names in canonical contract order."""

        return tuple(name for name, _value in self._configured_values)

    @staticmethod
    def _optional_value(environ: Mapping[str, str], name: str) -> str | None:
        value = environ.get(name)
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise TypeError(f"runtime configuration {name} must be a string")
        return value

    @classmethod
    def _optional_path(cls, value: str | None) -> Path | None:
        return None if value is None else cls._resolved_path(value)

    @classmethod
    def _path_or_default(cls, value: str | None, default: Path) -> Path:
        return cls._optional_path(value) or default.resolve()

    @staticmethod
    def _resolved_path(value: str | Path) -> Path:
        return Path(value).expanduser().resolve()

    @classmethod
    def _optional_resolved_string(cls, value: str | None) -> str | None:
        return None if value is None else str(cls._resolved_path(value))

    @staticmethod
    def _discover_weavec(source_root: Path | None) -> str | None:
        candidates: list[Path] = []
        installed = shutil.which("weavec")
        if installed:
            candidates.append(Path(installed))
        if source_root is not None:
            candidates.append(source_root / "build" / "weavec")
        candidates.extend(
            [
                Path.cwd() / "weavec" / "build" / "weavec",
                Path.cwd().parent / "weavec" / "build" / "weavec",
                Path(__file__).resolve().parents[3] / "weavec" / "build" / "weavec",
            ]
        )
        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate.resolve())
        return None


__all__ = ["PUBLIC_CONFIGURATION_VARIABLES", "RuntimeConfig"]
