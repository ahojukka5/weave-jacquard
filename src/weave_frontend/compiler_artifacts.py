"""Verified build artifact storage and non-destructive publication."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from .errors import ValidationError

BUILD_KEY_FORMAT = "weave-build-key-v4"


class CompilerArtifactMixin:
    """Artifact hashing, verification, cache admission, and publication."""

    @classmethod
    def _artifact_hashes(
        cls,
        sources: list[Any],
        *,
        diagnostics_path: Path,
        compiler_manifest_path: Path,
        compiler_diagnostics_path: Path,
        executable_path: Path,
        base: Path,
    ) -> dict[str, str]:
        hashes: dict[str, str] = {}
        for item in sources:
            hashes[str(item.source_path.relative_to(base))] = cls._sha256_file(
                item.source_path
            )
            hashes[str(item.map_path.relative_to(base))] = cls._sha256_file(
                item.map_path
            )
        hashes["diagnostics.json"] = cls._sha256_file(diagnostics_path)
        if compiler_manifest_path.is_file():
            hashes["compiler-manifest.json"] = cls._sha256_file(
                compiler_manifest_path
            )
        if compiler_diagnostics_path.is_file():
            hashes["compiler-diagnostics.json"] = cls._sha256_file(
                compiler_diagnostics_path
            )
        if executable_path.is_file():
            hashes["program"] = cls._sha256_file(executable_path)
        return hashes

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def _relativize_json_file(cls, path: Path, base: Path) -> None:
        value = json.loads(path.read_text(encoding="utf-8"))
        cls._write_json(path, cls._relativize_value(value, base))

    @classmethod
    def _relativize_value(cls, value: Any, base: Path) -> Any:
        if isinstance(value, str):
            prefix = str(base) + os.sep
            return value[len(prefix) :] if value.startswith(prefix) else value
        if isinstance(value, list):
            return [cls._relativize_value(item, base) for item in value]
        if isinstance(value, dict):
            return {
                key: cls._relativize_value(item, base)
                for key, item in value.items()
            }
        return value

    @classmethod
    def _relative_command(cls, command: list[str], base: Path) -> list[str]:
        return [str(cls._relativize_value(argument, base)) for argument in command]

    @classmethod
    def _with_artifact_paths(
        cls,
        manifest: dict[str, Any],
        directory: Path,
    ) -> dict[str, Any]:
        manifest["build_directory"] = str(directory)
        manifest["artifact_paths"] = cls._resolve_artifact_value(
            manifest["artifacts"],
            directory,
        )
        return manifest

    @classmethod
    def _resolve_artifact_value(cls, value: Any, directory: Path) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            path = cls._artifact_path(directory, value)
            if path is None:
                raise ValidationError(
                    "INVALID_ARTIFACT_PATH",
                    f"artifact path escapes its build directory: {value!r}",
                )
            return str(path)
        if isinstance(value, list):
            return [cls._resolve_artifact_value(item, directory) for item in value]
        if isinstance(value, dict):
            return {
                key: cls._resolve_artifact_value(item, directory)
                for key, item in value.items()
            }
        raise TypeError(f"unsupported artifact manifest value: {type(value).__name__}")

    @staticmethod
    def _artifact_path(directory: Path, value: Any) -> Path | None:
        if not isinstance(value, str) or not value:
            return None
        relative = Path(value)
        if relative.is_absolute():
            return None
        try:
            root = directory.resolve()
            resolved = (root / relative).resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            return None
        return resolved

    @classmethod
    def _artifact_references(cls, value: Any) -> Iterator[str]:
        if value is None:
            return
        if isinstance(value, str):
            yield value
            return
        if isinstance(value, list):
            for item in value:
                yield from cls._artifact_references(item)
            return
        if isinstance(value, dict):
            for item in value.values():
                yield from cls._artifact_references(item)
            return
        raise ValidationError(
            "INVALID_BUILD_MANIFEST",
            f"unsupported artifact manifest value: {type(value).__name__}",
        )

    @staticmethod
    def _valid_sha256(value: Any) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        )

    @classmethod
    def _verify_artifacts(
        cls,
        manifest: dict[str, Any],
        directory: Path,
    ) -> None:
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, dict):
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "build manifest artifacts must be an object",
            )
        references = set(cls._artifact_references(artifacts))
        if not references:
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "build manifest must reference at least one artifact",
            )
        hashes = manifest.get("artifact_sha256")
        if not isinstance(hashes, dict) or set(hashes) != references:
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "artifact hash keys must exactly match referenced artifacts",
            )
        for relative in sorted(references):
            path = cls._artifact_path(directory, relative)
            if path is None:
                raise ValidationError(
                    "INVALID_ARTIFACT_PATH",
                    f"artifact path escapes its build directory: {relative!r}",
                )
            if not path.is_file():
                raise ValidationError(
                    "CORRUPT_BUILD_ARTIFACT",
                    f"build artifact is missing or not a regular file: {relative!r}",
                )
            expected = hashes[relative]
            if not cls._valid_sha256(expected):
                raise ValidationError(
                    "INVALID_BUILD_MANIFEST",
                    f"artifact hash is not lowercase SHA-256: {relative!r}",
                )
            if cls._sha256_file(path) != expected:
                raise ValidationError(
                    "CORRUPT_BUILD_ARTIFACT",
                    f"build artifact checksum does not match: {relative!r}",
                )

    @staticmethod
    def _valid_build_id(value: Any) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 32
            and all(character in "0123456789abcdef" for character in value)
        )

    @classmethod
    def _read_verified_manifest(
        cls,
        directory: Path,
        *,
        expected_build_id: str | None = None,
    ) -> dict[str, Any]:
        manifest_path = directory / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                f"cannot read build manifest: {exc}",
            ) from exc
        if not isinstance(manifest, dict):
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "build manifest root must be an object",
            )
        if manifest.get("format") != "weave-frontend-build-manifest-v2":
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                f"unsupported build manifest format: {manifest.get('format')!r}",
            )
        build_id = manifest.get("build_id")
        if not cls._valid_build_id(build_id):
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "build manifest ID must be 32 lowercase hexadecimal characters",
            )
        if expected_build_id is not None and build_id != expected_build_id:
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "build manifest ID does not match its artifact directory",
            )
        if manifest.get("status") not in {"succeeded", "failed"}:
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "build manifest status must be 'succeeded' or 'failed'",
            )
        build_key_format = manifest.get("build_key_format")
        if not isinstance(build_key_format, str) or not build_key_format:
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "build manifest build_key_format must be a non-empty string",
            )
        returncode = manifest.get("returncode")
        if returncode is not None and (
            not isinstance(returncode, int) or isinstance(returncode, bool)
        ):
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "build manifest returncode must be an integer or null",
            )
        if not isinstance(manifest.get("compiler_diagnostics_protocol_valid"), bool):
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "compiler diagnostics protocol validity must be boolean",
            )
        compiler_manifest_valid = manifest.get("compiler_manifest_protocol_valid")
        if build_key_format == BUILD_KEY_FORMAT and not isinstance(
            compiler_manifest_valid, bool
        ):
            raise ValidationError(
                "INVALID_BUILD_MANIFEST",
                "compiler manifest protocol validity must be boolean",
            )
        cls._verify_artifacts(manifest, directory)
        return manifest

    @classmethod
    def _read_successful_manifest(
        cls,
        directory: Path,
        *,
        expected_build_id: str | None = None,
    ) -> dict[str, Any] | None:
        if not (directory / "manifest.json").is_file():
            return None
        try:
            manifest = cls._read_verified_manifest(
                directory,
                expected_build_id=expected_build_id,
            )
            artifacts = manifest.get("artifacts")
            if not isinstance(artifacts, dict):
                return None
            sources = artifacts.get("sources")
            node_maps = artifacts.get("node_maps")
            if manifest.get("status") != "succeeded":
                return None
            if manifest.get("returncode") != 0:
                return None
            if manifest.get("build_key_format") != BUILD_KEY_FORMAT:
                return None
            if manifest.get("compiler_diagnostics_protocol_valid") is not True:
                return None
            if manifest.get("compiler_manifest_protocol_valid") is not True:
                return None
            if artifacts.get("executable") != "program":
                return None
            if artifacts.get("compiler_manifest") != "compiler-manifest.json":
                return None
            if artifacts.get("compiler_diagnostics") != "compiler-diagnostics.json":
                return None
            if not isinstance(sources, list) or not sources:
                return None
            if not isinstance(node_maps, list) or len(node_maps) != len(sources):
                return None
            return cls._with_artifact_paths(manifest, directory)
        except (ValidationError, TypeError):
            return None

    @staticmethod
    @contextmanager
    def _publication_lock(final: Path) -> Iterator[None]:
        lock_path = final.parent / f".{final.name}.lock"
        with lock_path.open("a+b") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _remove_path(path: Path) -> None:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.exists():
            shutil.rmtree(path)

    @classmethod
    def _publish_directory(cls, temporary: Path, final: Path) -> None:
        cls._read_verified_manifest(
            temporary,
            expected_build_id=final.name,
        )
        with cls._publication_lock(final):
            if cls._read_successful_manifest(
                final,
                expected_build_id=final.name,
            ) is not None:
                cls._remove_path(temporary)
                return

            quarantine: Path | None = None
            if os.path.lexists(final):
                quarantine = final.parent / f".{final.name}.replaced-{uuid4().hex}"
                os.replace(final, quarantine)
            try:
                os.replace(temporary, final)
            except Exception:
                if quarantine is not None and not os.path.lexists(final):
                    os.replace(quarantine, final)
                raise
            else:
                if quarantine is not None:
                    cls._remove_path(quarantine)
