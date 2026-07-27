"""Revisioned behavioral test definitions stored as structural project metadata."""

from __future__ import annotations

import re
from typing import Any

from .errors import NotFoundError, ValidationError
from .project_metadata import BUILD_TARGET_PREFIX, TEST_TARGET_PREFIX
from .sexpr import JsonObject, head_symbol, make_atom, make_form, validate_tree

TEST_TARGET_HEAD = "test-target"
TEST_TARGET_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
TEST_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
MAX_TEST_ARGUMENTS = 64
MAX_TEST_TAGS = 32
MAX_TEST_STRING_BYTES = 262_144
MAX_TEST_TIMEOUT_MS = 300_000
MAX_TEST_MEMORY_BYTES = 16 * 1024 * 1024 * 1024
MAX_TEST_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_TEST_FILE_BYTES = 1024 * 1024 * 1024
DEFAULT_TIMEOUT_MS = 5_000
DEFAULT_MEMORY_BYTES = 256 * 1024 * 1024
DEFAULT_OUTPUT_BYTES = 64 * 1024
DEFAULT_FILE_BYTES = 1024 * 1024


class TestTargetRegistry:
    """Create and inspect immutable, revision-bound behavioral test definitions."""

    def __init__(self, workspace: Any) -> None:
        self.workspace = workspace

    def set(
        self,
        project: str,
        branch: str,
        name: str,
        build_target: str,
        *,
        arguments: list[str] | None = None,
        stdin: str = "",
        expected_exit_code: int = 0,
        expected_stdout: str = "",
        expected_stderr: str = "",
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        max_memory_bytes: int = DEFAULT_MEMORY_BYTES,
        max_output_bytes: int = DEFAULT_OUTPUT_BYTES,
        max_file_bytes: int = DEFAULT_FILE_BYTES,
        tags: list[str] | None = None,
        expected_revision_id: str | None = None,
        author: str = "test-agent",
    ) -> dict[str, Any]:
        test_name = self._validate_name(name)
        config = self._config(
            test_name,
            build_target,
            arguments=arguments,
            stdin=stdin,
            expected_exit_code=expected_exit_code,
            expected_stdout=expected_stdout,
            expected_stderr=expected_stderr,
            timeout_ms=timeout_ms,
            max_memory_bytes=max_memory_bytes,
            max_output_bytes=max_output_bytes,
            max_file_bytes=max_file_bytes,
            tags=tags,
        )
        base_revision_id, state = self.workspace._state_for_write(
            project,
            branch,
            expected_revision_id=expected_revision_id,
        )
        self._require_build_target(state, config["build_target"])
        storage_document = self._storage_document(test_name)
        root = self._build_tree(config, existing=state.get(storage_document))
        validate_tree(root)
        state[storage_document] = root
        revision_id = self.workspace._commit(
            project,
            branch,
            state,
            message=f"set test target {test_name}",
            author=author,
            operations=[("set_test_target", storage_document, config)],
            expected_branch_heads={branch: base_revision_id},
            stale_error_code="STALE_BRANCH_HEAD",
        )
        return {
            **config,
            "branch": branch,
            "base_revision_id": base_revision_id,
            "revision_id": revision_id,
            "storage_document": storage_document,
            "root_node_id": root["id"],
        }

    def delete(
        self,
        project: str,
        branch: str,
        name: str,
        *,
        expected_revision_id: str | None = None,
        author: str = "test-agent",
    ) -> dict[str, Any]:
        test_name = self._validate_name(name)
        base_revision_id, state = self.workspace._state_for_write(
            project,
            branch,
            expected_revision_id=expected_revision_id,
        )
        storage_document = self._storage_document(test_name)
        if storage_document not in state:
            raise NotFoundError(f"test target {test_name!r} not found")
        del state[storage_document]
        revision_id = self.workspace._commit(
            project,
            branch,
            state,
            message=f"delete test target {test_name}",
            author=author,
            operations=[("delete_test_target", storage_document, {"name": test_name})],
            expected_branch_heads={branch: base_revision_id},
            stale_error_code="STALE_BRANCH_HEAD",
        )
        return {
            "name": test_name,
            "branch": branch,
            "base_revision_id": base_revision_id,
            "revision_id": revision_id,
            "deleted": True,
        }

    def get(
        self,
        project: str,
        name: str,
        *,
        branch: str = "main",
        revision_id: str | None = None,
    ) -> dict[str, Any]:
        test_name = self._validate_name(name)
        revision = revision_id or self.workspace.branch_head(project, branch)
        self._require_project_revision(project, revision)
        state = self.workspace._state_at_revision(revision)
        storage_document = self._storage_document(test_name)
        try:
            root = state[storage_document]
        except KeyError as exc:
            raise NotFoundError(f"test target {test_name!r} not found") from exc
        config = self._parse_tree(root, name=test_name)
        self._require_build_target(state, config["build_target"])
        return {
            **config,
            "branch": branch,
            "revision_id": revision,
            "storage_document": storage_document,
            "root_node_id": root["id"],
        }

    def list(
        self,
        project: str,
        *,
        branch: str = "main",
        revision_id: str | None = None,
    ) -> list[dict[str, Any]]:
        revision = revision_id or self.workspace.branch_head(project, branch)
        self._require_project_revision(project, revision)
        state = self.workspace._state_at_revision(revision)
        result: list[dict[str, Any]] = []
        for storage_document, root in sorted(state.items()):
            if not storage_document.startswith(TEST_TARGET_PREFIX):
                continue
            name = storage_document[len(TEST_TARGET_PREFIX) :]
            config = self._parse_tree(root, name=name)
            self._require_build_target(state, config["build_target"])
            result.append(
                {
                    **config,
                    "branch": branch,
                    "revision_id": revision,
                    "storage_document": storage_document,
                    "root_node_id": root["id"],
                }
            )
        return result

    def _require_project_revision(self, project: str, revision_id: str) -> None:
        row = self.workspace.db.connection.execute(
            """SELECT 1
               FROM revisions r
               JOIN projects p ON p.id = r.project_id
               WHERE r.id = ? AND p.name = ?""",
            (revision_id, project),
        ).fetchone()
        if row is None:
            raise NotFoundError(
                f"revision {revision_id!r} does not belong to project {project!r}"
            )

    @staticmethod
    def _require_build_target(state: dict[str, JsonObject], name: str) -> None:
        storage_document = f"{BUILD_TARGET_PREFIX}{name}"
        root = state.get(storage_document)
        if root is None or head_symbol(root) != "build-target":
            raise NotFoundError(f"build target {name!r} not found")

    @staticmethod
    def _validate_name(name: str) -> str:
        if not isinstance(name, str) or not TEST_TARGET_NAME.fullmatch(name):
            raise ValidationError(
                "INVALID_TEST_TARGET_NAME",
                "test target name must use letters, digits, '.', '_', or '-'",
            )
        return name

    @staticmethod
    def _storage_document(name: str) -> str:
        return f"{TEST_TARGET_PREFIX}{name}"

    @classmethod
    def _config(
        cls,
        name: str,
        build_target: str,
        *,
        arguments: list[str] | None,
        stdin: str,
        expected_exit_code: int,
        expected_stdout: str,
        expected_stderr: str,
        timeout_ms: int,
        max_memory_bytes: int,
        max_output_bytes: int,
        max_file_bytes: int,
        tags: list[str] | None,
    ) -> dict[str, Any]:
        if not isinstance(build_target, str) or not TEST_TARGET_NAME.fullmatch(build_target):
            raise ValidationError(
                "INVALID_TEST_BUILD_TARGET",
                "build_target must be a valid non-empty target name",
            )
        normalized_arguments = cls._validate_strings(
            "arguments",
            arguments or [],
            maximum=MAX_TEST_ARGUMENTS,
            unique=False,
        )
        normalized_tags = cls._validate_strings(
            "tags",
            tags or [],
            maximum=MAX_TEST_TAGS,
            unique=True,
            pattern=TEST_TAG,
        )
        for field, value in (
            ("stdin", stdin),
            ("expected_stdout", expected_stdout),
            ("expected_stderr", expected_stderr),
        ):
            cls._validate_text(field, value)
        cls._validate_integer("expected_exit_code", expected_exit_code, 0, 255)
        cls._validate_integer("timeout_ms", timeout_ms, 1, MAX_TEST_TIMEOUT_MS)
        cls._validate_integer(
            "max_memory_bytes",
            max_memory_bytes,
            1,
            MAX_TEST_MEMORY_BYTES,
        )
        cls._validate_integer(
            "max_output_bytes",
            max_output_bytes,
            1,
            MAX_TEST_OUTPUT_BYTES,
        )
        cls._validate_integer(
            "max_file_bytes",
            max_file_bytes,
            0,
            MAX_TEST_FILE_BYTES,
        )
        return {
            "name": name,
            "build_target": build_target,
            "arguments": normalized_arguments,
            "stdin": stdin,
            "expected_exit_code": expected_exit_code,
            "expected_stdout": expected_stdout,
            "expected_stderr": expected_stderr,
            "timeout_ms": timeout_ms,
            "max_memory_bytes": max_memory_bytes,
            "max_output_bytes": max_output_bytes,
            "max_file_bytes": max_file_bytes,
            "network_policy": "deny",
            "filesystem_policy": "isolated",
            "tags": normalized_tags,
        }

    @staticmethod
    def _validate_text(field: str, value: Any) -> None:
        if not isinstance(value, str):
            raise ValidationError(
                "INVALID_TEST_TARGET",
                f"{field} must be a string",
            )
        if len(value.encode("utf-8")) > MAX_TEST_STRING_BYTES:
            raise ValidationError(
                "INVALID_TEST_TARGET",
                f"{field} exceeds {MAX_TEST_STRING_BYTES} UTF-8 bytes",
            )

    @classmethod
    def _validate_strings(
        cls,
        field: str,
        values: Any,
        *,
        maximum: int,
        unique: bool,
        pattern: re.Pattern[str] | None = None,
    ) -> list[str]:
        if not isinstance(values, list) or len(values) > maximum:
            raise ValidationError(
                "INVALID_TEST_TARGET",
                f"{field} must be a list with at most {maximum} items",
            )
        result: list[str] = []
        for value in values:
            cls._validate_text(field, value)
            if pattern is not None and not pattern.fullmatch(value):
                raise ValidationError(
                    "INVALID_TEST_TARGET",
                    f"{field} contains an invalid value {value!r}",
                )
            result.append(value)
        if unique and len(result) != len(set(result)):
            raise ValidationError(
                "INVALID_TEST_TARGET",
                f"{field} must not contain duplicates",
            )
        return result

    @staticmethod
    def _validate_integer(field: str, value: Any, minimum: int, maximum: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError(
                "INVALID_TEST_TARGET",
                f"{field} must be an integer",
            )
        if value < minimum or value > maximum:
            raise ValidationError(
                "INVALID_TEST_TARGET",
                f"{field} must be between {minimum} and {maximum}",
            )

    @classmethod
    def _build_tree(
        cls,
        config: dict[str, Any],
        *,
        existing: JsonObject | None,
    ) -> JsonObject:
        existing_fields = cls._existing_fields(existing)
        root = cls._form_with_identity(TEST_TARGET_HEAD, existing)
        fields: list[tuple[str, str, Any]] = [
            ("build-target", "string", config["build_target"]),
        ]
        fields.extend(("arg", "string", value) for value in config["arguments"])
        fields.extend(
            [
                ("stdin", "string", config["stdin"]),
                ("expect-exit", "integer", config["expected_exit_code"]),
                ("expect-stdout", "string", config["expected_stdout"]),
                ("expect-stderr", "string", config["expected_stderr"]),
                ("timeout-ms", "integer", config["timeout_ms"]),
                ("max-memory-bytes", "integer", config["max_memory_bytes"]),
                ("max-output-bytes", "integer", config["max_output_bytes"]),
                ("max-file-bytes", "integer", config["max_file_bytes"]),
                ("network", "string", config["network_policy"]),
                ("filesystem", "string", config["filesystem_policy"]),
            ]
        )
        fields.extend(("tag", "string", value) for value in config["tags"])
        used: dict[str, int] = {}
        for head, kind, value in fields:
            index = used.get(head, 0)
            existing_values = existing_fields.get(head, [])
            current = existing_values[index] if index < len(existing_values) else None
            root["children"].append(cls._field(head, kind, value, existing=current))
            used[head] = index + 1
        return root

    @classmethod
    def _parse_tree(cls, root: JsonObject, *, name: str) -> dict[str, Any]:
        validate_tree(root)
        if head_symbol(root) != TEST_TARGET_HEAD:
            raise ValidationError(
                "INVALID_TEST_TARGET",
                f"test target {name!r} has invalid root form",
            )
        fields = cls._existing_fields(root)
        allowed = {
            "build-target",
            "arg",
            "stdin",
            "expect-exit",
            "expect-stdout",
            "expect-stderr",
            "timeout-ms",
            "max-memory-bytes",
            "max-output-bytes",
            "max-file-bytes",
            "network",
            "filesystem",
            "tag",
        }
        unknown = sorted(set(fields) - allowed)
        if unknown:
            raise ValidationError(
                "INVALID_TEST_TARGET",
                f"test target {name!r} has unknown fields {unknown!r}",
            )
        single = {
            "build-target": "string",
            "stdin": "string",
            "expect-exit": "integer",
            "expect-stdout": "string",
            "expect-stderr": "string",
            "timeout-ms": "integer",
            "max-memory-bytes": "integer",
            "max-output-bytes": "integer",
            "max-file-bytes": "integer",
            "network": "string",
            "filesystem": "string",
        }
        values: dict[str, Any] = {}
        for field, kind in single.items():
            entries = fields.get(field, [])
            if len(entries) != 1:
                raise ValidationError(
                    "INVALID_TEST_TARGET",
                    f"test target {name!r} requires exactly one {field!r} field",
                )
            values[field] = cls._field_value(entries[0], kind=kind, field=field)
        arguments = [
            cls._field_value(entry, kind="string", field="arg")
            for entry in fields.get("arg", [])
        ]
        tags = [
            cls._field_value(entry, kind="string", field="tag")
            for entry in fields.get("tag", [])
        ]
        config = cls._config(
            name,
            values["build-target"],
            arguments=arguments,
            stdin=values["stdin"],
            expected_exit_code=values["expect-exit"],
            expected_stdout=values["expect-stdout"],
            expected_stderr=values["expect-stderr"],
            timeout_ms=values["timeout-ms"],
            max_memory_bytes=values["max-memory-bytes"],
            max_output_bytes=values["max-output-bytes"],
            max_file_bytes=values["max-file-bytes"],
            tags=tags,
        )
        if values["network"] != "deny" or values["filesystem"] != "isolated":
            raise ValidationError(
                "INVALID_TEST_TARGET",
                "test targets require network='deny' and filesystem='isolated'",
            )
        return config

    @staticmethod
    def _field_value(field: JsonObject, *, kind: str, field: str) -> Any:
        children = field.get("children", [])
        if len(children) != 2 or children[1].get("kind") != kind:
            raise ValidationError(
                "INVALID_TEST_TARGET",
                f"field {field!r} must contain one {kind} value",
            )
        return children[1]["value"]

    @staticmethod
    def _form_with_identity(head: str, existing: JsonObject | None) -> JsonObject:
        root_id = existing.get("id") if isinstance(existing, dict) else None
        head_id: str | None = None
        if isinstance(existing, dict):
            children = existing.get("children", [])
            if children and isinstance(children[0], dict):
                head_id = children[0].get("id")
        form = make_form(head, node_id=root_id)
        if head_id is not None:
            form["children"][0]["id"] = head_id
        return form

    @classmethod
    def _field(
        cls,
        head: str,
        kind: str,
        value: Any,
        *,
        existing: JsonObject | None,
    ) -> JsonObject:
        field = cls._form_with_identity(head, existing)
        value_id: str | None = None
        if isinstance(existing, dict):
            children = existing.get("children", [])
            if len(children) == 2 and isinstance(children[1], dict):
                value_id = children[1].get("id")
        field["children"].append(make_atom(kind, value, node_id=value_id))
        return field

    @staticmethod
    def _existing_fields(existing: JsonObject | None) -> dict[str, list[JsonObject]]:
        fields: dict[str, list[JsonObject]] = {}
        if not isinstance(existing, dict) or head_symbol(existing) != TEST_TARGET_HEAD:
            return fields
        for child in existing.get("children", [])[1:]:
            if not isinstance(child, dict):
                continue
            head = head_symbol(child)
            if head is not None:
                fields.setdefault(head, []).append(child)
        return fields
