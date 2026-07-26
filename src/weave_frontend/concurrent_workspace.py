"""Race-safe public workspace for program and node mutations."""

from __future__ import annotations

from typing import Any

from .concurrent_sexpr import SExpressionWorkspace as _NodeConcurrentWorkspace
from .errors import ValidationError
from .sexpr import make_atom, make_form, parse_source, validate_tree


class SExpressionWorkspace(_NodeConcurrentWorkspace):
    """Public workspace whose program and node writes compare-and-set branches."""

    def create_program(
        self,
        project: str,
        branch: str,
        document: str,
        *,
        program_name: str,
        version: str = "0.1",
        expected_revision_id: str | None = None,
        author: str = "agent",
    ) -> dict[str, Any]:
        base_revision_id, state = self._state_for_write(
            project,
            branch,
            expected_revision_id=expected_revision_id,
        )
        if document in state:
            raise ValidationError(
                "DUPLICATE_DOCUMENT",
                f"document {document!r} already exists",
            )
        root = make_form("program")
        name_form = make_form("name")
        name_form["children"].append(make_atom("string", program_name))
        version_form = make_form("version")
        version_form["children"].append(make_atom("string", version))
        root["children"].extend([name_form, version_form])
        validate_tree(root)
        state[document] = root
        revision = self._commit_program_mutation(
            project,
            branch,
            base_revision_id,
            state,
            message=f"create program {document}",
            author=author,
            operation=("create_program", root["id"], {"document": document}),
        )
        result = self._mutation_result(
            revision,
            branch,
            document,
            root,
            [root["id"]],
        )
        result["base_revision_id"] = base_revision_id
        return result

    def import_program(
        self,
        project: str,
        branch: str,
        document: str,
        source: str,
        *,
        replace: bool = False,
        expected_revision_id: str | None = None,
        author: str = "agent",
    ) -> dict[str, Any]:
        root = parse_source(source)
        base_revision_id, state = self._state_for_write(
            project,
            branch,
            expected_revision_id=expected_revision_id,
        )
        if document in state and not replace:
            raise ValidationError(
                "DUPLICATE_DOCUMENT",
                f"document {document!r} already exists",
            )
        state[document] = root
        revision = self._commit_program_mutation(
            project,
            branch,
            base_revision_id,
            state,
            message=f"{'replace' if replace else 'import'} program {document}",
            author=author,
            operation=("import_program", root["id"], {"document": document}),
        )
        result = self._mutation_result(
            revision,
            branch,
            document,
            root,
            [root["id"]],
        )
        result["base_revision_id"] = base_revision_id
        return result

    def _commit_program_mutation(
        self,
        project: str,
        branch: str,
        base_revision_id: str,
        state: dict[str, dict[str, Any]],
        *,
        message: str,
        author: str,
        operation: tuple[str, str | None, dict[str, Any]],
    ) -> str:
        return self._commit(
            project,
            branch,
            state,
            message=message,
            author=author,
            operations=[operation],
            expected_branch_heads={branch: base_revision_id},
            stale_error_code="STALE_BRANCH_HEAD",
        )
