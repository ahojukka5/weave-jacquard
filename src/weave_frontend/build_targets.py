"""Revisioned named build targets stored as structural project metadata."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from .errors import NotFoundError, ValidationError
from .sexpr import JsonObject, head_symbol, make_atom, make_form, validate_tree

BUILD_TARGET_PREFIX = "@build-target/"
BUILD_TARGET_HEAD = "build-target"
NATIVE_COMPILER_TARGET = "native"
BUILD_TARGET_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class BuildTargetRegistry:
    """Create, inspect, and build immutable revisioned target definitions."""

    def __init__(self, workspace: Any) -> None:
        self.workspace = workspace

    def set(
        self,
        project: str,
        branch: str,
        name: str,
        document: str,
        *,
        additional_documents: list[str] | None = None,
        compiler_target: str | None = None,
        author: str = "agent",
    ) -> dict[str, Any]:
        target_name = self._validate_name(name)
        documents = self._validate_document_set(document, additional_documents)
        effective_target = self._normalize_compiler_target(compiler_target)
        state = self.workspace._state(project, branch)
        self._require_program_documents(state, documents)
        storage_document = self._storage_document(target_name)
        root = self._build_tree(
            document,
            documents[1:],
            effective_target,
            existing=state.get(storage_document),
        )
        validate_tree(root)
        state[storage_document] = root
        config = self._config(
            target_name,
            document,
            documents[1:],
            effective_target,
        )
        revision = self.workspace._commit(
            project,
            branch,
            state,
            message=f"set build target {target_name}",
            author=author,
            operations=[("set_build_target", storage_document, config)],
        )
        return {
            **config,
            "branch": branch,
            "revision_id": revision,
            "storage_document": storage_document,
            "root_node_id": root["id"],
        }

    def delete(
        self,
        project: str,
        branch: str,
        name: str,
        *,
        author: str = "agent",
    ) -> dict[str, Any]:
        target_name = self._validate_name(name)
        state = self.workspace._state(project, branch)
        storage_document = self._storage_document(target_name)
        if storage_document not in state:
            raise NotFoundError(f"build target {target_name!r} not found")
        del state[storage_document]
        revision = self.workspace._commit(
            project,
            branch,
            state,
            message=f"delete build target {target_name}",
            author=author,
            operations=[
                ("delete_build_target", storage_document, {"name": target_name})
            ],
        )
        return {
            "name": target_name,
            "branch": branch,
            "revision_id": revision,
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
        target_name = self._validate_name(name)
        revision = revision_id or self.workspace.branch_head(project, branch)
        self._require_project_revision(project, revision)
        state = self.workspace._state_at_revision(revision)
        storage_document = self._storage_document(target_name)
        try:
            root = state[storage_document]
        except KeyError as exc:
            raise NotFoundError(f"build target {target_name!r} not found") from exc
        config = self._parse_tree(root, name=target_name)
        self._require_program_documents(
            state,
            [config["document"], *config["additional_documents"]],
        )
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
            if not storage_document.startswith(BUILD_TARGET_PREFIX):
                continue
            name = storage_document[len(BUILD_TARGET_PREFIX) :]
            result.append(
                {
                    **self._parse_tree(root, name=name),
                    "branch": branch,
                    "revision_id": revision,
                    "storage_document": storage_document,
                    "root_node_id": root["id"],
                }
            )
        return result

    def build(
        self,
        bridge: Any,
        project: str,
        name: str,
        *,
        branch: str = "main",
        revision_id: str | None = None,
    ) -> dict[str, Any]:
        revision = revision_id or self.workspace.branch_head(project, branch)
        config = self.get(
            project,
            name,
            branch=branch,
            revision_id=revision,
        )
        result = bridge.build(
            project,
            config["document"],
            additional_documents=config["additional_documents"],
            branch=branch,
            revision_id=revision,
            target=(
                None
                if config["compiler_target"] == NATIVE_COMPILER_TARGET
                else config["compiler_target"]
            ),
        )
        result["build_target"] = {
            key: config[key]
            for key in (
                "name",
                "document",
                "additional_documents",
                "compiler_target",
            )
        }
        result["build_target"]["revision_id"] = revision
        return result

    def program_documents(
        self,
        project: str,
        *,
        branch: str = "main",
        revision_id: str | None = None,
    ) -> list[str]:
        revision = revision_id or self.workspace.branch_head(project, branch)
        self._require_project_revision(project, revision)
        return sorted(
            name
            for name in self.workspace._state_at_revision(revision)
            if not name.startswith(BUILD_TARGET_PREFIX)
        )

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
    def _validate_name(name: str) -> str:
        if not isinstance(name, str) or not BUILD_TARGET_NAME.fullmatch(name):
            raise ValidationError(
                "INVALID_BUILD_TARGET_NAME",
                "build target name must use letters, digits, '.', '_', or '-'",
            )
        return name

    @staticmethod
    def _normalize_compiler_target(value: str | None) -> str:
        if value is None:
            return NATIVE_COMPILER_TARGET
        if not isinstance(value, str) or not value:
            raise ValidationError(
                "INVALID_COMPILER_TARGET",
                "compiler_target must be a non-empty string or null",
            )
        return value

    @staticmethod
    def _validate_document_set(
        document: str,
        additional_documents: list[str] | None,
    ) -> list[str]:
        values: list[Any] = [document]
        if additional_documents is not None:
            if not isinstance(additional_documents, list):
                raise ValidationError(
                    "INVALID_DOCUMENT_SET",
                    "additional_documents must be a list of document names",
                )
            values.extend(additional_documents)
        if any(not isinstance(value, str) or not value for value in values):
            raise ValidationError(
                "INVALID_DOCUMENT_SET",
                "document names must be non-empty strings",
            )
        documents = [str(value) for value in values]
        if any(value.startswith(BUILD_TARGET_PREFIX) for value in documents):
            raise ValidationError(
                "INVALID_BUILD_DOCUMENT",
                "reserved build-target metadata cannot be compiled as source",
            )
        if len(documents) != len(set(documents)):
            raise ValidationError(
                "DUPLICATE_BUILD_DOCUMENT",
                "a document may appear only once in one build target",
            )
        return documents

    @staticmethod
    def _require_program_documents(
        state: dict[str, JsonObject],
        documents: list[str],
    ) -> None:
        for document in documents:
            if document.startswith(BUILD_TARGET_PREFIX) or document not in state:
                raise NotFoundError(f"program document {document!r} not found")

    @staticmethod
    def _storage_document(name: str) -> str:
        return f"{BUILD_TARGET_PREFIX}{name}"

    @staticmethod
    def _config(
        name: str,
        document: str,
        additional_documents: list[str],
        compiler_target: str,
    ) -> dict[str, Any]:
        return {
            "name": name,
            "document": document,
            "additional_documents": list(additional_documents),
            "compiler_target": compiler_target,
        }

    @classmethod
    def _build_tree(
        cls,
        document: str,
        additional_documents: list[str],
        compiler_target: str,
        *,
        existing: JsonObject | None,
    ) -> JsonObject:
        existing_fields = cls._existing_fields(existing)
        root = cls._form_with_identity(BUILD_TARGET_HEAD, existing)
        root["children"].append(
            cls._field(
                "primary",
                document,
                existing=cls._first(existing_fields, "primary"),
            )
        )
        existing_sources = existing_fields.get("source", [])
        for index, source in enumerate(additional_documents):
            current = existing_sources[index] if index < len(existing_sources) else None
            root["children"].append(
                cls._field(
                    "source",
                    source,
                    existing=current,
                    deterministic_seed=(
                        None if current is not None else f"{root['id']}\0source\0{source}"
                    ),
                )
            )
        root["children"].append(
            cls._field(
                "compiler-target",
                compiler_target,
                existing=cls._first(existing_fields, "compiler-target"),
            )
        )
        return root

    @classmethod
    def _field(
        cls,
        head: str,
        value: str,
        *,
        existing: JsonObject | None,
        deterministic_seed: str | None = None,
    ) -> JsonObject:
        if existing is not None:
            field = cls._form_with_identity(head, existing)
            children = existing.get("children", [])
            value_id = (
                children[1].get("id")
                if len(children) == 2 and isinstance(children[1], dict)
                else None
            )
        elif deterministic_seed is not None:
            field = make_form(
                head,
                node_id=cls._stable_node_id(deterministic_seed, "field"),
            )
            field["children"][0]["id"] = cls._stable_node_id(
                deterministic_seed,
                "head",
            )
            value_id = cls._stable_node_id(deterministic_seed, "value")
        else:
            field = make_form(head)
            value_id = None
        field["children"].append(make_atom("string", value, node_id=value_id))
        return field

    @staticmethod
    def _stable_node_id(seed: str, role: str) -> str:
        digest = hashlib.sha256(f"{seed}\0{role}".encode("utf-8")).hexdigest()
        return f"n_{digest[:16]}"

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

    @staticmethod
    def _first(
        fields: dict[str, list[JsonObject]],
        head: str,
    ) -> JsonObject | None:
        values = fields.get(head, [])
        return values[0] if values else None

    @staticmethod
    def _existing_fields(existing: JsonObject | None) -> dict[str, list[JsonObject]]:
        fields: dict[str, list[JsonObject]] = {}
        if not isinstance(existing, dict) or head_symbol(existing) != BUILD_TARGET_HEAD:
            return fields
        for child in existing.get("children", [])[1:]:
            head = head_symbol(child)
            if head is not None:
                fields.setdefault(head, []).append(child)
        return fields

    @classmethod
    def _parse_tree(cls, root: JsonObject, *, name: str) -> dict[str, Any]:
        validate_tree(root)
        if head_symbol(root) != BUILD_TARGET_HEAD:
            raise cls._invalid_tree(name, "root form must be build-target")
        fields: dict[str, list[str]] = {}
        for field in root.get("children", [])[1:]:
            head = head_symbol(field)
            if head not in {"primary", "source", "compiler-target"}:
                raise cls._invalid_tree(name, f"unknown field {head!r}")
            fields.setdefault(head, []).append(
                cls._field_value(field, target_name=name)
            )
        if len(fields.get("primary", [])) != 1:
            raise cls._invalid_tree(name, "exactly one primary field is required")
        if len(fields.get("compiler-target", [])) != 1:
            raise cls._invalid_tree(
                name,
                "exactly one compiler-target field is required",
            )
        primary = fields["primary"][0]
        sources = fields.get("source", [])
        cls._validate_document_set(primary, sources)
        return cls._config(
            name,
            primary,
            sources,
            fields["compiler-target"][0],
        )

    @staticmethod
    def _field_value(field: JsonObject, *, target_name: str) -> str:
        children = field.get("children", [])
        if len(children) != 2:
            raise BuildTargetRegistry._invalid_tree(
                target_name,
                "each field must contain exactly one value",
            )
        value = children[1]
        if value.get("kind") != "string" or not value.get("value"):
            raise BuildTargetRegistry._invalid_tree(
                target_name,
                "field values must be non-empty strings",
            )
        return str(value["value"])

    @staticmethod
    def _invalid_tree(name: str, message: str) -> ValidationError:
        return ValidationError(
            "INVALID_BUILD_TARGET",
            f"build target {name!r}: {message}",
        )
