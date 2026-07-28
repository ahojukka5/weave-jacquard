"""Content-derived identity for one running Jacquard MCP application."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import stat
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .bounded_process import run_bounded_process
from .database import SCHEMA_VERSION
from .errors import ValidationError

RUNTIME_IDENTITY_FORMAT = "weave-jacquard-runtime-identity-v1"
CONFIGURATION_VALUE_ID_FORMAT = "weave-jacquard-configuration-value-v1"
MAX_RUNTIME_VERSION_BYTES = 4_096
RUNTIME_VERSION_TIMEOUT_SECONDS = 5

ApplicationManifestProvider = Callable[[], Mapping[str, Any]]


class RuntimeIdentityService:
    """Report application, database, compiler, and sandbox runtime identity."""

    def __init__(
        self,
        workspace: Any,
        compiler: Any,
        sandbox: Any,
        application_manifest_provider: ApplicationManifestProvider,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.workspace = workspace
        self.compiler = compiler
        self.sandbox = sandbox
        self.application_manifest_provider = application_manifest_provider
        self.environ = os.environ if environ is None else environ

    def report(self) -> dict[str, Any]:
        """Return one configuration-value-redacted content-derived identity report."""

        application = self._application_identity()
        configuration_variables = application["configuration_variables"]
        configured_variables = [
            name
            for name in configuration_variables
            if bool(self.environ.get(name))
        ]
        payload = {
            "format": RUNTIME_IDENTITY_FORMAT,
            "jacquard": {
                "version": self._distribution_version("weave-jacquard"),
                "application_id": application["application_id"],
                "tool_manifest_id": application["tool_manifest_id"],
                "tool_count": application["tool_count"],
                "capability_count": application["capability_count"],
            },
            "python": {
                "implementation": platform.python_implementation(),
                "version": platform.python_version(),
                "executable_sha256": self._optional_binary_sha256(
                    Path(sys.executable).resolve()
                ),
            },
            "mcp": {
                "version": self._distribution_version("mcp"),
            },
            "database": {
                "schema_version": SCHEMA_VERSION,
                "busy_timeout_ms": int(self.workspace.db.busy_timeout_ms),
                "journal_mode": str(
                    self.workspace.db.connection.execute(
                        "PRAGMA journal_mode"
                    ).fetchone()[0]
                ).lower(),
                "foreign_keys": bool(
                    self.workspace.db.connection.execute(
                        "PRAGMA foreign_keys"
                    ).fetchone()[0]
                ),
                "location_id": self._opaque_value_id(
                    "database_path",
                    str(Path(self.workspace.db.path).resolve()),
                ),
            },
            "compiler": self._compiler_identity(),
            "sandbox": self._sandbox_identity(),
            "configuration": {
                "variables": configuration_variables,
                "configured_variables": configured_variables,
                "value_ids": {
                    name: self._opaque_value_id(name, self.environ[name])
                    for name in configured_variables
                },
                "values_redacted": True,
            },
        }
        return {
            **payload,
            "runtime_id": self._hash_json(payload),
        }

    def _application_identity(self) -> dict[str, Any]:
        manifest = self.application_manifest_provider()
        if not isinstance(manifest, Mapping):
            raise RuntimeError("application manifest provider returned a non-mapping")
        capabilities = manifest.get("capabilities")
        variables = manifest.get("configuration_variables")
        if not isinstance(capabilities, list) or not all(
            isinstance(item, Mapping) for item in capabilities
        ):
            raise RuntimeError("application manifest capabilities are invalid")
        if not isinstance(variables, list) or not all(
            isinstance(item, str) and item for item in variables
        ):
            raise RuntimeError(
                "application manifest configuration variables are invalid"
            )
        for field in ("application_id", "tool_manifest_id"):
            value = manifest.get(field)
            if not self._valid_sha256(value):
                raise RuntimeError(f"application manifest {field} is invalid")
        tool_count = manifest.get("tool_count")
        if (
            isinstance(tool_count, bool)
            or not isinstance(tool_count, int)
            or tool_count <= 0
        ):
            raise RuntimeError("application manifest tool_count is invalid")
        return {
            "application_id": manifest["application_id"],
            "tool_manifest_id": manifest["tool_manifest_id"],
            "tool_count": tool_count,
            "capability_count": len(capabilities),
            "configuration_variables": sorted(variables),
        }

    def _compiler_identity(self) -> dict[str, Any]:
        try:
            path = self.compiler._compiler_path()
        except ValidationError as exc:
            return {
                "available": False,
                "binary": None,
                "version": None,
                "error": self._redacted_compiler_error(exc),
            }
        except OSError:
            return self._compiler_identity_failure()

        try:
            binary = self._binary_identity(path)
            result = run_bounded_process(
                [path, "--version"],
                timeout_seconds=RUNTIME_VERSION_TIMEOUT_SECONDS,
                max_output_bytes=MAX_RUNTIME_VERSION_BYTES,
            )
        except (OSError, ValueError):
            return self._compiler_identity_failure()

        output = "\n".join(
            part.strip()
            for part in (result.stdout, result.stderr)
            if part.strip()
        )
        version = " ".join(output.splitlines()) or None
        if result.timed_out:
            error = {
                "code": "WEAVEC_VERSION_TIMEOUT",
                "message": (
                    "weavec --version exceeded "
                    f"{RUNTIME_VERSION_TIMEOUT_SECONDS} seconds"
                ),
            }
        elif result.output_limited:
            error = {
                "code": "WEAVEC_VERSION_OUTPUT_LIMIT",
                "message": (
                    "weavec --version exceeded "
                    f"{MAX_RUNTIME_VERSION_BYTES} captured bytes"
                ),
            }
        elif result.returncode != 0:
            error = {
                "code": "WEAVEC_VERSION_FAILED",
                "message": f"weavec --version exited {result.returncode}",
            }
        elif version is None:
            error = {
                "code": "WEAVEC_VERSION_EMPTY",
                "message": "weavec --version returned no identity",
            }
        else:
            error = None
        return {
            "available": error is None,
            "binary": binary,
            "version": version,
            "error": error,
        }

    @staticmethod
    def _redacted_compiler_error(error: ValidationError) -> dict[str, Any]:
        messages = {
            "WEAVEC_NOT_FOUND": (
                "weavec was not found; configure WEAVEC_BIN or install it on PATH"
            ),
            "WEAVEC_NOT_EXECUTABLE": "the configured weavec is not executable",
        }
        return {
            "code": error.code,
            "message": messages.get(error.code, "weavec identity is unavailable"),
            "node_id": error.node_id,
        }

    @staticmethod
    def _compiler_identity_failure() -> dict[str, Any]:
        return {
            "available": False,
            "binary": None,
            "version": None,
            "error": {
                "code": "WEAVEC_IDENTITY_FAILED",
                "message": "weavec binary identity or version probing failed",
            },
        }

    def _sandbox_identity(self) -> dict[str, Any]:
        try:
            raw_capabilities = self.sandbox.capabilities()
        except Exception:
            return {
                "available": False,
                "capabilities": None,
                "bubblewrap_binary": None,
                "prlimit_binary": None,
                "error": {
                    "code": "SANDBOX_IDENTITY_FAILED",
                    "message": "sandbox capability probing failed",
                },
            }
        if not isinstance(raw_capabilities, dict):
            raise RuntimeError("sandbox capabilities are not an object")
        capabilities = dict(raw_capabilities)
        if capabilities.get("probe_error") is not None:
            capabilities["probe_error"] = "sandbox capability probe failed"
        return {
            "available": capabilities.get("available") is True,
            "capabilities": capabilities,
            "bubblewrap_binary": self._optional_binary_identity(
                getattr(self.sandbox, "executable", None)
            ),
            "prlimit_binary": self._optional_binary_identity(
                getattr(self.sandbox, "prlimit", None)
            ),
            "error": None,
        }

    @classmethod
    def _optional_binary_identity(cls, value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        try:
            return cls._binary_identity(Path(value).resolve())
        except (OSError, ValueError):
            return {
                "available": False,
                "bytes": None,
                "sha256": None,
                "error": "runtime binary identity is unavailable",
            }

    @classmethod
    def _optional_binary_sha256(cls, path: Path) -> str | None:
        try:
            return str(cls._binary_identity(path)["sha256"])
        except (OSError, ValueError):
            return None

    @staticmethod
    def _binary_identity(path: Path) -> dict[str, Any]:
        flags = os.O_RDONLY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("runtime binary must be a regular file")
            digest = hashlib.sha256()
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            after = os.fstat(descriptor)
            identity_before = (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            )
            identity_after = (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            )
            if identity_before != identity_after:
                raise ValueError("runtime binary changed while hashing")
            return {
                "available": True,
                "bytes": before.st_size,
                "sha256": digest.hexdigest(),
                "error": None,
            }
        finally:
            os.close(descriptor)

    @staticmethod
    def _distribution_version(name: str) -> str | None:
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return None

    @staticmethod
    def _opaque_value_id(name: str, value: str) -> str:
        encoded = (
            CONFIGURATION_VALUE_ID_FORMAT.encode("utf-8")
            + b"\0"
            + name.encode("utf-8")
            + b"\0"
            + value.encode("utf-8")
        )
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _valid_sha256(value: Any) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        )

    @staticmethod
    def _hash_json(value: Any) -> str:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "CONFIGURATION_VALUE_ID_FORMAT",
    "MAX_RUNTIME_VERSION_BYTES",
    "RUNTIME_IDENTITY_FORMAT",
    "RUNTIME_VERSION_TIMEOUT_SECONDS",
    "RuntimeIdentityService",
]
