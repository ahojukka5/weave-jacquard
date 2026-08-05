"""Bounded consumer for the compiler-authoritative ``weavec`` registry."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..bounded_process import run_bounded_process
from ..errors import ValidationError
from ..grammar_help import GrammarIndex
from ..sexpr import JsonObject, head_symbol
from .validator import WeavecValidator

CAPABILITIES_FORMAT = "weavec-capabilities-v1"
CAPABILITIES_SCHEMA_ID = "urn:weavec:schema:capabilities:v1"
CAPABILITIES_SCHEMA_VERSION = 1
CAPABILITIES_TIMEOUT_SECONDS = 5
MAX_CAPABILITIES_BYTES = 1024 * 1024
EXPECTED_SURFACE_VERSION = "weave-surface-v1"
EXPECTED_GRAMMAR_ID = "weave-surface-grammar-v1"
EXPECTED_WIR_CORE_VERSION = 2
REQUIRED_PROTOCOLS = {
    "weavec-capabilities-v1": 1,
    "weavec-build-manifest-v1": 1,
    "weavec-diagnostics-v1": 1,
    "weavec-compilation-trace-v1": 1,
    "weave-wir-core-v2": 2,
}


def _invalid(code: str, message: str) -> ValidationError:
    return ValidationError(code, message)


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(
            "WEAVEC_CAPABILITIES_INVALID",
            f"weavec capability field {field} must be an object",
        )
    return value


def _sequence(value: Any, field: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _invalid(
            "WEAVEC_CAPABILITIES_INVALID",
            f"weavec capability field {field} must be an array",
        )
    return value


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise _invalid(
            "WEAVEC_CAPABILITIES_INVALID",
            f"weavec capability field {field} must be a non-empty string",
        )
    return value


def _positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _invalid(
            "WEAVEC_CAPABILITIES_INVALID",
            f"weavec capability field {field} must be a positive integer",
        )
    return value


class WeavecCapabilities:
    """Load and validate one immutable final-compiler capability document."""

    def __init__(
        self,
        binary: str | Path | None = None,
        *,
        source_root: str | Path | None = None,
        environment_fallback: bool = True,
        timeout_seconds: float = CAPABILITIES_TIMEOUT_SECONDS,
        max_output_bytes: int = MAX_CAPABILITIES_BYTES,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if isinstance(max_output_bytes, bool) or max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be a positive integer")
        self._configured_binary = binary
        self.source_root = Path(source_root).resolve() if source_root else None
        self.environment_fallback = environment_fallback
        self.timeout_seconds = float(timeout_seconds)
        self.max_output_bytes = max_output_bytes
        self._cache: dict[str, dict[str, Any]] = {}

    def load(self) -> dict[str, Any]:
        """Return a validated registry cached by exact compiler binary SHA-256."""

        binary = self._resolve_binary()
        binary_identity = self._binary_identity(binary)
        compiler_sha256 = str(binary_identity["sha256"])
        cached = self._cache.get(compiler_sha256)
        if cached is not None:
            return dict(cached)

        try:
            result = run_bounded_process(
                [binary, "capabilities", "--json"],
                timeout_seconds=self.timeout_seconds,
                max_output_bytes=self.max_output_bytes,
            )
        except OSError as exc:
            raise _invalid(
                "WEAVEC_CAPABILITIES_UNAVAILABLE",
                "weavec capabilities --json could not start",
            ) from exc

        if result.timed_out:
            raise _invalid(
                "WEAVEC_CAPABILITIES_TIMEOUT",
                f"weavec capabilities --json exceeded {self.timeout_seconds:g} seconds",
            )
        if result.output_limited:
            raise _invalid(
                "WEAVEC_CAPABILITIES_OUTPUT_LIMIT",
                "weavec capabilities --json exceeded the bounded output size",
            )
        if result.returncode != 0:
            raise _invalid(
                "WEAVEC_CAPABILITIES_FAILED",
                f"weavec capabilities --json exited {result.returncode}",
            )
        if "\ufffd" in result.stdout:
            raise _invalid(
                "WEAVEC_CAPABILITIES_INVALID_UTF8",
                "weavec capabilities --json did not return valid UTF-8",
            )
        try:
            document = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise _invalid(
                "WEAVEC_CAPABILITIES_INVALID_JSON",
                "weavec capabilities --json returned malformed JSON",
            ) from exc
        validated = self._validate(document)
        registry_bytes = result.stdout.encode("utf-8")
        identity = {
            "format": CAPABILITIES_FORMAT,
            "sha256": hashlib.sha256(registry_bytes).hexdigest(),
            "bytes": len(registry_bytes),
            "compiler_sha256": compiler_sha256,
            "compiler_bytes": binary_identity["bytes"],
            "compiler_version": validated["compiler"]["version"],
            "surface_version": validated["language"]["surface_version"],
            "grammar_id": validated["language"]["grammar_id"],
            "wir_core_version": validated["language"]["wir_core_version"],
            "default_target": validated["targets"]["default"],
        }
        result_document = {
            **validated,
            "_jacquard_identity": identity,
        }
        self._cache = {compiler_sha256: result_document}
        return dict(result_document)

    def identity(self) -> dict[str, Any]:
        """Return path-free identity for the validated compiler registry."""

        return dict(self.load()["_jacquard_identity"])

    def require(
        self,
        *,
        command: str | None = None,
        protocols: Sequence[str] = (),
        target: str | None = None,
    ) -> dict[str, Any]:
        """Require advertised public capabilities before invoking the compiler."""

        document = self.load()
        commands = {
            item["name"]: item for item in document["commands"] if isinstance(item, Mapping)
        }
        command_item: Mapping[str, Any] | None = None
        if command is not None:
            command_item = commands.get(command)
            if command_item is None or command_item.get("status") not in {
                "stable",
                "experimental",
            }:
                raise _invalid(
                    "WEAVEC_CAPABILITY_MISSING",
                    f"installed weavec does not advertise command {command!r}",
                )
        protocol_map = {
            item["id"]: item["version"]
            for item in document["protocols"]
            if isinstance(item, Mapping)
        }
        for protocol in protocols:
            if protocol not in protocol_map:
                raise _invalid(
                    "WEAVEC_PROTOCOL_UNSUPPORTED",
                    f"installed weavec does not advertise protocol {protocol!r}",
                )
        if target is not None:
            installed = {
                item["triple"]
                for item in document["targets"]["installed"]
                if isinstance(item, Mapping)
            }
            if target != "native" and target not in installed:
                raise _invalid(
                    "WEAVEC_TARGET_UNSUPPORTED",
                    f"installed weavec does not advertise target {target!r}",
                )
        return document

    def form(self, head: str) -> Mapping[str, Any] | None:
        """Return one compiler-authoritative surface form by exact head."""

        for item in self.load()["surface"]["forms"]:
            if isinstance(item, Mapping) and item.get("head") == head:
                return item
        return None

    def search_forms(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        """Search authoritative form heads and canonical replacements."""

        needle = query.casefold()
        results: list[dict[str, Any]] = []
        for item in self.load()["surface"]["forms"]:
            if not isinstance(item, Mapping):
                continue
            head = str(item["head"])
            replacement = item.get("canonical_replacement")
            if needle not in head.casefold() and not (
                isinstance(replacement, str) and needle in replacement.casefold()
            ):
                continue
            results.append(self._form_summary(item))
        results.sort(
            key=lambda item: (
                not item["form"].casefold().startswith(needle),
                item["form"],
            )
        )
        return results[:limit]

    @staticmethod
    def _form_summary(item: Mapping[str, Any]) -> dict[str, Any]:
        arity = _mapping(item["arity"], "surface.forms[].arity")
        return {
            "form": item["head"],
            "authority": "weavec-capabilities-v1",
            "status": item["status"],
            "min_children": arity["min_children"],
            "max_children": arity["max_children"],
            "type_information": item["type_information"],
            "feature": item["feature"],
            "canonical_replacement": item["canonical_replacement"],
            "roles": list(item["roles"]),
        }

    def _resolve_binary(self) -> Path:
        configured = self._configured_binary
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
        raise _invalid(
            "WEAVEC_NOT_FOUND",
            "weavec was not found; configure WEAVEC_BIN or install it on PATH",
        )

    @staticmethod
    def _binary_identity(path: Path) -> dict[str, Any]:
        flags = os.O_RDONLY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise _invalid(
                "WEAVEC_NOT_EXECUTABLE",
                "the configured weavec cannot be opened safely",
            ) from exc
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise _invalid(
                    "WEAVEC_NOT_EXECUTABLE",
                    "the configured weavec is not a regular file",
                )
            digest = hashlib.sha256()
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            after = os.fstat(descriptor)
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ):
                raise _invalid(
                    "WEAVEC_CHANGED_DURING_IDENTITY",
                    "the configured weavec changed while being identified",
                )
            return {
                "bytes": before.st_size,
                "sha256": digest.hexdigest(),
            }
        finally:
            os.close(descriptor)

    @classmethod
    def _validate(cls, raw: Any) -> dict[str, Any]:
        document = dict(_mapping(raw, "root"))
        if document.get("format") != CAPABILITIES_FORMAT:
            raise _invalid(
                "WEAVEC_CAPABILITIES_FORMAT_UNSUPPORTED",
                "installed weavec does not emit weavec-capabilities-v1",
            )
        if document.get("schema_id") != CAPABILITIES_SCHEMA_ID:
            raise _invalid(
                "WEAVEC_CAPABILITIES_SCHEMA_UNSUPPORTED",
                "installed weavec capability schema identifier is incompatible",
            )
        if document.get("schema_version") != CAPABILITIES_SCHEMA_VERSION:
            raise _invalid(
                "WEAVEC_CAPABILITIES_SCHEMA_UNSUPPORTED",
                "installed weavec capability schema version is incompatible",
            )

        compiler = _mapping(document.get("compiler"), "compiler")
        if compiler.get("name") != "weavec" or compiler.get("public_variant") != "final":
            raise _invalid(
                "WEAVEC_VARIANT_UNSUPPORTED",
                "Jacquard requires the final user-facing weavec compiler",
            )
        _nonempty_string(compiler.get("version"), "compiler.version")

        language = _mapping(document.get("language"), "language")
        if (
            language.get("name") != "Weave"
            or language.get("surface_version") != EXPECTED_SURFACE_VERSION
            or language.get("grammar_id") != EXPECTED_GRAMMAR_ID
            or language.get("syntax") != "s-expression"
            or language.get("case_sensitive") is not True
            or language.get("wir_core_version") != EXPECTED_WIR_CORE_VERSION
        ):
            raise _invalid(
                "WEAVEC_LANGUAGE_UNSUPPORTED",
                "installed weavec language or WIR contract is incompatible",
            )

        protocols = cls._validate_protocols(document.get("protocols"))
        commands = cls._validate_commands(document.get("commands"), protocols)
        targets = cls._validate_targets(document.get("targets"))
        features = cls._validate_features(document.get("features"))
        surface = cls._validate_surface(document.get("surface"), features)
        return {
            **document,
            "compiler": dict(compiler),
            "language": dict(language),
            "protocols": protocols,
            "commands": commands,
            "targets": targets,
            "features": features,
            "surface": surface,
        }

    @staticmethod
    def _validate_protocols(raw: Any) -> list[dict[str, Any]]:
        protocols: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, raw_item in enumerate(_sequence(raw, "protocols")):
            item = _mapping(raw_item, f"protocols[{index}]")
            protocol_id = _nonempty_string(item.get("id"), f"protocols[{index}].id")
            version = _positive_integer(item.get("version"), f"protocols[{index}].version")
            _nonempty_string(item.get("kind"), f"protocols[{index}].kind")
            if protocol_id in seen:
                raise _invalid(
                    "WEAVEC_CAPABILITIES_INVALID",
                    f"duplicate compiler protocol {protocol_id!r}",
                )
            seen.add(protocol_id)
            protocols.append(dict(item))
            expected = REQUIRED_PROTOCOLS.get(protocol_id)
            if expected is not None and version != expected:
                raise _invalid(
                    "WEAVEC_PROTOCOL_UNSUPPORTED",
                    f"compiler protocol {protocol_id!r} has incompatible version {version}",
                )
        for protocol_id in REQUIRED_PROTOCOLS:
            if protocol_id not in seen:
                raise _invalid(
                    "WEAVEC_PROTOCOL_UNSUPPORTED",
                    f"installed weavec does not advertise protocol {protocol_id!r}",
                )
        return protocols

    @staticmethod
    def _validate_commands(
        raw: Any,
        protocols: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        known_protocols = {str(item["id"]) for item in protocols}
        commands: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, raw_item in enumerate(_sequence(raw, "commands")):
            item = _mapping(raw_item, f"commands[{index}]")
            name = _nonempty_string(item.get("name"), f"commands[{index}].name")
            _nonempty_string(item.get("spelling"), f"commands[{index}].spelling")
            _nonempty_string(item.get("audience"), f"commands[{index}].audience")
            if item.get("status") not in {"stable", "experimental"}:
                raise _invalid(
                    "WEAVEC_CAPABILITIES_INVALID",
                    f"commands[{index}].status is invalid",
                )
            command_protocols = _sequence(item.get("protocols"), f"commands[{index}].protocols")
            if any(
                not isinstance(value, str) or value not in known_protocols
                for value in command_protocols
            ):
                raise _invalid(
                    "WEAVEC_CAPABILITIES_INVALID",
                    f"commands[{index}] references an unknown protocol",
                )
            if name in seen:
                raise _invalid(
                    "WEAVEC_CAPABILITIES_INVALID",
                    f"duplicate compiler command {name!r}",
                )
            seen.add(name)
            commands.append(dict(item))
        for name in ("capabilities", "build", "frontend"):
            if name not in seen:
                raise _invalid(
                    "WEAVEC_CAPABILITY_MISSING",
                    f"installed weavec does not advertise command {name!r}",
                )
        return commands

    @staticmethod
    def _validate_targets(raw: Any) -> dict[str, Any]:
        targets = _mapping(raw, "targets")
        default = _nonempty_string(targets.get("default"), "targets.default")
        installed: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, raw_item in enumerate(_sequence(targets.get("installed"), "targets.installed")):
            item = _mapping(raw_item, f"targets.installed[{index}]")
            triple = _nonempty_string(item.get("triple"), f"targets.installed[{index}].triple")
            for field in ("native", "cross_compilation"):
                if not isinstance(item.get(field), bool):
                    raise _invalid(
                        "WEAVEC_CAPABILITIES_INVALID",
                        f"targets.installed[{index}].{field} must be boolean",
                    )
            _nonempty_string(item.get("runtime"), f"targets.installed[{index}].runtime")
            for field in ("optimization_levels", "cpu_selection"):
                values = _sequence(item.get(field), f"targets.installed[{index}].{field}")
                if any(not isinstance(value, str) for value in values):
                    raise _invalid(
                        "WEAVEC_CAPABILITIES_INVALID",
                        f"targets.installed[{index}].{field} must contain strings",
                    )
            if triple in seen:
                raise _invalid(
                    "WEAVEC_CAPABILITIES_INVALID",
                    f"duplicate installed compiler target {triple!r}",
                )
            seen.add(triple)
            installed.append(dict(item))
        if not installed or default not in seen:
            raise _invalid(
                "WEAVEC_CAPABILITIES_INVALID",
                "compiler default target must be present in installed targets",
            )
        return {**dict(targets), "default": default, "installed": installed}

    @staticmethod
    def _validate_features(raw: Any) -> list[dict[str, Any]]:
        features: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, raw_item in enumerate(_sequence(raw, "features")):
            item = _mapping(raw_item, f"features[{index}]")
            feature_id = _nonempty_string(item.get("id"), f"features[{index}].id")
            if item.get("status") not in {"stable", "experimental", "planned"}:
                raise _invalid(
                    "WEAVEC_CAPABILITIES_INVALID",
                    f"features[{index}].status is invalid",
                )
            issue = item.get("issue")
            if issue is not None:
                _positive_integer(issue, f"features[{index}].issue")
            if feature_id in seen:
                raise _invalid(
                    "WEAVEC_CAPABILITIES_INVALID",
                    f"duplicate compiler feature {feature_id!r}",
                )
            seen.add(feature_id)
            features.append(dict(item))
        return features

    @staticmethod
    def _validate_surface(
        raw: Any,
        features: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        surface = _mapping(raw, "surface")
        _nonempty_string(surface.get("grammar_document"), "surface.grammar_document")
        _nonempty_string(surface.get("canonical_document"), "surface.canonical_document")
        if surface.get("child_count_excludes_head") is not True:
            raise _invalid(
                "WEAVEC_CAPABILITIES_INVALID",
                "surface child counts must explicitly exclude the list head",
            )
        feature_ids = {str(item["id"]) for item in features}
        forms: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, raw_item in enumerate(_sequence(surface.get("forms"), "surface.forms")):
            item = _mapping(raw_item, f"surface.forms[{index}]")
            head = _nonempty_string(item.get("head"), f"surface.forms[{index}].head")
            if item.get("status") not in {
                "canonical",
                "compatibility",
                "deprecated",
                "experimental",
            }:
                raise _invalid(
                    "WEAVEC_CAPABILITIES_INVALID",
                    f"surface.forms[{index}].status is invalid",
                )
            arity = _mapping(item.get("arity"), f"surface.forms[{index}].arity")
            minimum = arity.get("min_children")
            maximum = arity.get("max_children")
            if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 0:
                raise _invalid(
                    "WEAVEC_CAPABILITIES_INVALID",
                    f"surface.forms[{index}].arity.min_children is invalid",
                )
            if maximum is not None and (
                isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < minimum
            ):
                raise _invalid(
                    "WEAVEC_CAPABILITIES_INVALID",
                    f"surface.forms[{index}].arity.max_children is invalid",
                )
            if item.get("type_information") not in {
                "none",
                "explicit",
                "contextual",
                "semantic",
            }:
                raise _invalid(
                    "WEAVEC_CAPABILITIES_INVALID",
                    f"surface.forms[{index}].type_information is invalid",
                )
            feature = item.get("feature")
            if feature is not None and feature not in feature_ids:
                raise _invalid(
                    "WEAVEC_CAPABILITIES_INVALID",
                    f"surface.forms[{index}] references an unknown feature",
                )
            replacement = item.get("canonical_replacement")
            if replacement is not None and not isinstance(replacement, str):
                raise _invalid(
                    "WEAVEC_CAPABILITIES_INVALID",
                    f"surface.forms[{index}].canonical_replacement is invalid",
                )
            roles = _sequence(item.get("roles"), f"surface.forms[{index}].roles")
            if any(not isinstance(role, Mapping) for role in roles):
                raise _invalid(
                    "WEAVEC_CAPABILITIES_INVALID",
                    f"surface.forms[{index}].roles must contain objects",
                )
            if head in seen:
                raise _invalid(
                    "WEAVEC_CAPABILITIES_INVALID",
                    f"duplicate compiler surface form {head!r}",
                )
            seen.add(head)
            forms.append({**dict(item), "arity": dict(arity), "roles": list(roles)})
        if not forms:
            raise _invalid(
                "WEAVEC_CAPABILITIES_INVALID",
                "compiler surface registry contains no forms",
            )
        for field in (
            "types",
            "operators",
            "casts",
            "contextual_literals",
            "compatibility_families",
        ):
            _sequence(surface.get(field), f"surface.{field}")
        return {**dict(surface), "forms": forms}


class CapabilityGrammarIndex(GrammarIndex):
    """Combine compiler-authoritative forms with observational corpus examples."""

    def __init__(
        self,
        source_root: str | Path | None = None,
        *,
        capabilities: WeavecCapabilities,
    ) -> None:
        self.capabilities = capabilities
        self.capability_error: dict[str, Any] | None = None
        self.capability_identity: dict[str, Any] | None = None
        try:
            self.capability_identity = capabilities.identity()
        except ValidationError as exc:
            self.capability_error = exc.as_dict()
        super().__init__(source_root)

    def help(
        self,
        *,
        form: str | None = None,
        query: str | None = None,
        parent_form: str | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        result = super().help(
            form=form,
            query=query,
            parent_form=parent_form,
            limit=limit,
        )
        if form and self.capability_identity is not None:
            authoritative = self.capabilities.form(form)
            if authoritative is not None:
                result["found"] = True
                result["authoritative"] = self.capabilities._form_summary(authoritative)
        if query and self.capability_identity is not None:
            authoritative_matches = self.capabilities.search_forms(query, limit=limit)
            result["authoritative_matches"] = authoritative_matches
        result.update(self._capability_status())
        return result

    def hint_for_node(self, node: JsonObject) -> dict[str, Any] | None:
        observed = super().hint_for_node(node)
        head = head_symbol(node)
        if head is None or self.capability_identity is None:
            return observed
        authoritative = self.capabilities.form(head)
        if authoritative is None:
            return observed
        summary = self.capabilities._form_summary(authoritative)
        actual = len(node.get("children", [])) - 1
        minimum = int(summary["min_children"])
        maximum = summary["max_children"]
        return {
            **(observed or {}),
            **summary,
            "known": True,
            "actual_arity": actual,
            "complete_by_authoritative_arity": (
                actual >= minimum and (maximum is None or actual <= int(maximum))
            ),
            "observational": observed,
        }

    def status(self) -> dict[str, Any]:
        return {
            **super().status(),
            **self._capability_status(),
            "authority": "weavec-capabilities-v1",
            "observational_examples": "configured weavec correctness corpus",
        }

    def _capability_status(self) -> dict[str, Any]:
        return {
            "compiler_registry_available": self.capability_identity is not None,
            "compiler_registry": self.capability_identity,
            "compiler_registry_error": self.capability_error,
        }


class CapabilityAwareWeavecValidator(WeavecValidator):
    """Validate only after the installed compiler advertises the frontend contract."""

    def __init__(
        self,
        binary: str | Path | None = None,
        source_root: str | Path | None = None,
        *,
        capabilities: WeavecCapabilities,
        timeout_seconds: int = 30,
        max_output_bytes: int,
        max_wir_bytes: int,
        environment_fallback: bool = True,
    ) -> None:
        super().__init__(
            binary,
            source_root,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
            max_wir_bytes=max_wir_bytes,
            environment_fallback=environment_fallback,
        )
        self.capabilities = capabilities

    def validate_sources(self, sources: list[tuple[str, str]]) -> dict[str, Any]:
        try:
            registry = self.capabilities.require(
                command="frontend",
                protocols=("weave-wir-core-v2",),
            )
        except ValidationError as exc:
            return {
                "available": False,
                "valid": None,
                "returncode": None,
                "diagnostic": exc.message,
                "capability_error": exc.as_dict(),
                "documents": [document for document, _ in sources],
            }
        result = super().validate_sources(sources)
        result["compiler_capabilities"] = registry["_jacquard_identity"]
        return result


__all__ = [
    "CAPABILITIES_FORMAT",
    "CAPABILITIES_SCHEMA_ID",
    "CAPABILITIES_SCHEMA_VERSION",
    "CAPABILITIES_TIMEOUT_SECONDS",
    "CapabilityAwareWeavecValidator",
    "CapabilityGrammarIndex",
    "MAX_CAPABILITIES_BYTES",
    "WeavecCapabilities",
]
