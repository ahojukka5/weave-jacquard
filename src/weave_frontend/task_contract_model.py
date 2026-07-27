"""Structural model and cross-document validation for revisioned task contracts."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .errors import ValidationError
from .project_metadata import TASK_CONTRACT_PREFIX, is_project_metadata_document
from .sexpr import JsonObject, head_symbol, make_atom, make_form, validate_tree

TASK_CONTRACT_FORMAT = "weave-task-contract-v1"
TASK_CONTRACT_HEAD = "task-contract"
TASK_CONTRACT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
TASK_CONTRACT_STATUSES = {
    "open",
    "in_progress",
    "blocked",
    "ready_for_review",
    "complete",
}
TASK_ACTIVE_STATUSES = {"open", "in_progress"}
MAX_TASK_TEXT_CHARS = 16_000
MAX_TASK_ITEMS = 64
MAX_TASK_ITEM_CHARS = 2_000
MAX_TASK_LIST_PAGE = 100

STATUS_TRANSITIONS = {
    "open": {"in_progress", "blocked", "complete"},
    "in_progress": {"blocked", "ready_for_review", "complete"},
    "blocked": {"in_progress"},
    "ready_for_review": {"in_progress", "complete"},
    "complete": set(),
}
_SINGLE_FIELDS = (
    ("format", "format"),
    ("name", "name"),
    ("branch", "branch"),
    ("base_revision_id", "base-revision"),
    ("owner", "owner"),
    ("objective", "objective"),
    ("status", "status"),
)
_LIST_FIELDS = (
    ("allowed_documents", "allowed-documents"),
    ("dependencies", "dependencies"),
    ("required_tests", "required-tests"),
    ("acceptance_criteria", "acceptance-criteria"),
)


def task_storage_document(name: str) -> str:
    return f"{TASK_CONTRACT_PREFIX}{validate_task_name(name)}"


def validate_task_name(value: Any) -> str:
    if not isinstance(value, str) or not TASK_CONTRACT_NAME.fullmatch(value):
        raise ValidationError(
            "INVALID_TASK_NAME",
            "task names must use letters, digits, '.', '_', or '-'",
        )
    return value


def validate_task_status(value: Any) -> str:
    if not isinstance(value, str) or value not in TASK_CONTRACT_STATUSES:
        raise ValidationError(
            "INVALID_TASK_STATUS",
            f"status must be one of {sorted(TASK_CONTRACT_STATUSES)}",
        )
    return value


def normalize_task_contract(
    *,
    name: Any,
    branch: Any,
    base_revision_id: Any,
    owner: Any,
    objective: Any,
    status: Any,
    allowed_documents: Any,
    dependencies: Any = None,
    required_tests: Any = None,
    acceptance_criteria: Any = None,
    expected_format: Any = TASK_CONTRACT_FORMAT,
) -> dict[str, Any]:
    if expected_format != TASK_CONTRACT_FORMAT:
        raise ValidationError(
            "INVALID_TASK_CONTRACT",
            f"task contract format must be {TASK_CONTRACT_FORMAT!r}",
        )
    return {
        "format": TASK_CONTRACT_FORMAT,
        "name": validate_task_name(name),
        "branch": _text("branch", branch, maximum=256),
        "base_revision_id": _text(
            "base_revision_id",
            base_revision_id,
            maximum=256,
        ),
        "owner": _text("owner", owner, maximum=256),
        "objective": _text(
            "objective",
            objective,
            maximum=MAX_TASK_TEXT_CHARS,
        ),
        "status": validate_task_status(status),
        "allowed_documents": _items(
            "allowed_documents",
            allowed_documents,
            require_nonempty=True,
        ),
        "dependencies": _items(
            "dependencies",
            dependencies or [],
            pattern=TASK_CONTRACT_NAME,
        ),
        "required_tests": _items(
            "required_tests",
            required_tests or [],
            pattern=TASK_CONTRACT_NAME,
        ),
        "acceptance_criteria": _items(
            "acceptance_criteria",
            acceptance_criteria or [],
        ),
    }


def task_contract_hash(config: dict[str, Any]) -> str:
    encoded = json.dumps(
        config,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_task_contract_tree(
    config: dict[str, Any],
    *,
    existing: JsonObject | None = None,
) -> JsonObject:
    old_fields = _field_map(existing)
    root = make_form(
        TASK_CONTRACT_HEAD,
        node_id=existing.get("id") if existing is not None else None,
    )
    for key, head in _SINGLE_FIELDS:
        old = old_fields.get(head)
        field = make_form(head, node_id=old.get("id") if old else None)
        old_atom = old.get("children", [None, None])[1] if old else None
        atom_id = old_atom.get("id") if isinstance(old_atom, dict) else None
        field["children"].append(make_atom("string", config[key], node_id=atom_id))
        root["children"].append(field)
    for key, head in _LIST_FIELDS:
        old = old_fields.get(head)
        field = make_form(head, node_id=old.get("id") if old else None)
        old_atoms = old.get("children", [])[1:] if old else []
        for index, value in enumerate(config[key]):
            atom_id = None
            if index < len(old_atoms) and isinstance(old_atoms[index], dict):
                atom_id = old_atoms[index].get("id")
            field["children"].append(make_atom("string", value, node_id=atom_id))
        root["children"].append(field)
    validate_tree(root)
    return root


def parse_task_contract_tree(root: JsonObject, *, name: str) -> dict[str, Any]:
    task_name = validate_task_name(name)
    if head_symbol(root) != TASK_CONTRACT_HEAD:
        raise ValidationError(
            "INVALID_TASK_CONTRACT",
            f"task {task_name!r} metadata must use {TASK_CONTRACT_HEAD!r}",
        )
    fields: dict[str, JsonObject] = {}
    for child in root.get("children", [])[1:]:
        field_head = head_symbol(child)
        if field_head is None or field_head in fields:
            raise ValidationError(
                "INVALID_TASK_CONTRACT",
                f"task {task_name!r} contains invalid or duplicate fields",
            )
        fields[field_head] = child
    expected_heads = {head for _, head in (*_SINGLE_FIELDS, *_LIST_FIELDS)}
    unknown = sorted(set(fields) - expected_heads)
    if unknown:
        raise ValidationError(
            "INVALID_TASK_CONTRACT",
            f"task {task_name!r} contains unknown fields {unknown!r}",
        )
    raw: dict[str, Any] = {}
    for key, head in _SINGLE_FIELDS:
        raw[key] = _single_value(fields.get(head), head)
    for key, head in _LIST_FIELDS:
        raw[key] = _list_values(fields.get(head), head)
    config = normalize_task_contract(
        name=raw["name"],
        branch=raw["branch"],
        base_revision_id=raw["base_revision_id"],
        owner=raw["owner"],
        objective=raw["objective"],
        status=raw["status"],
        allowed_documents=raw["allowed_documents"],
        dependencies=raw["dependencies"],
        required_tests=raw["required_tests"],
        acceptance_criteria=raw["acceptance_criteria"],
        expected_format=raw["format"],
    )
    if config["name"] != task_name:
        raise ValidationError(
            "INVALID_TASK_CONTRACT",
            f"task metadata name {config['name']!r} does not match {task_name!r}",
        )
    return config


def task_contracts_from_state(
    state: dict[str, JsonObject],
) -> dict[str, dict[str, Any]]:
    result = {}
    for document, root in sorted(state.items()):
        if not document.startswith(TASK_CONTRACT_PREFIX):
            continue
        name = document[len(TASK_CONTRACT_PREFIX) :]
        result[name] = parse_task_contract_tree(root, name=name)
    return result


def validate_task_contract_config_references(
    state: dict[str, JsonObject],
    config: dict[str, Any],
) -> None:
    for document in config["allowed_documents"]:
        if is_project_metadata_document(document) or document not in state:
            raise ValidationError(
                "INVALID_TASK_DOCUMENT_REFERENCE",
                f"task document {document!r} must be an existing compiler source",
            )
    for test_name in config["required_tests"]:
        if f"@test-target/{test_name}" not in state:
            raise ValidationError(
                "INVALID_TASK_TEST_REFERENCE",
                f"required test {test_name!r} does not exist",
            )
    for dependency in config["dependencies"]:
        if dependency == config["name"]:
            raise ValidationError(
                "INVALID_TASK_DEPENDENCY",
                "a task cannot depend on itself",
            )
        if task_storage_document(dependency) not in state:
            raise ValidationError(
                "INVALID_TASK_DEPENDENCY",
                f"task dependency {dependency!r} does not exist",
            )


def validate_task_contract_references(state: dict[str, JsonObject]) -> None:
    contracts = task_contracts_from_state(state)
    for config in contracts.values():
        validate_task_contract_config_references(state, config)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str, path: tuple[str, ...]) -> None:
        if name in visited:
            return
        if name in visiting:
            cycle_start = path.index(name)
            cycle = (*path[cycle_start:], name)
            raise ValidationError(
                "TASK_DEPENDENCY_CYCLE",
                f"task dependency cycle detected: {' -> '.join(cycle)}",
            )
        visiting.add(name)
        for dependency in contracts[name]["dependencies"]:
            visit(dependency, (*path, dependency))
        visiting.remove(name)
        visited.add(name)

    for task_name in sorted(contracts):
        visit(task_name, (task_name,))


def _field_map(root: JsonObject | None) -> dict[str, JsonObject]:
    if root is None:
        return {}
    return {
        str(head_symbol(child)): child
        for child in root.get("children", [])[1:]
        if head_symbol(child) is not None
    }


def _single_value(field: JsonObject | None, name: str) -> Any:
    if field is None or len(field.get("children", [])) != 2:
        raise ValidationError(
            "INVALID_TASK_CONTRACT",
            f"task field {name!r} requires exactly one value",
        )
    atom = field["children"][1]
    if atom.get("kind") != "string":
        raise ValidationError(
            "INVALID_TASK_CONTRACT",
            f"task field {name!r} requires one string",
        )
    return atom.get("value")


def _list_values(field: JsonObject | None, name: str) -> list[Any]:
    if field is None:
        raise ValidationError(
            "INVALID_TASK_CONTRACT",
            f"task field {name!r} is required",
        )
    values = []
    for atom in field.get("children", [])[1:]:
        if atom.get("kind") != "string":
            raise ValidationError(
                "INVALID_TASK_CONTRACT",
                f"task field {name!r} accepts only strings",
            )
        values.append(atom.get("value"))
    return values


def _text(name: str, value: Any, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(
            "INVALID_TASK_CONTRACT",
            f"{name} must be a non-empty string",
        )
    if len(value) > maximum:
        raise ValidationError(
            "INVALID_TASK_CONTRACT",
            f"{name} must contain at most {maximum} characters",
        )
    return value


def _items(
    name: str,
    values: Any,
    *,
    pattern: re.Pattern[str] | None = None,
    require_nonempty: bool = False,
) -> list[str]:
    if not isinstance(values, list) or len(values) > MAX_TASK_ITEMS:
        raise ValidationError(
            "INVALID_TASK_CONTRACT",
            f"{name} must be a list with at most {MAX_TASK_ITEMS} items",
        )
    normalized = [
        _text(f"{name} item", value, maximum=MAX_TASK_ITEM_CHARS)
        for value in values
    ]
    if require_nonempty and not normalized:
        raise ValidationError(
            "INVALID_TASK_CONTRACT",
            f"{name} must contain at least one item",
        )
    if pattern is not None and any(not pattern.fullmatch(value) for value in normalized):
        raise ValidationError(
            "INVALID_TASK_CONTRACT",
            f"{name} contains an invalid task or test name",
        )
    if len(normalized) != len(set(normalized)):
        raise ValidationError(
            "INVALID_TASK_CONTRACT",
            f"{name} must not contain duplicates",
        )
    return normalized
