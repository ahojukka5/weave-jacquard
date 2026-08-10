"""Cross-document integrity checks for revisioned build-target metadata."""

from __future__ import annotations

from ..errors import ValidationError
from ..project_metadata import is_project_metadata_document
from ..sexpr import JsonObject
from .targets import BUILD_TARGET_PREFIX, BuildTargetRegistry


def build_target_references(
    state: dict[str, JsonObject],
) -> dict[str, list[str]]:
    """Return program-document names to lexical build-target names."""

    references: dict[str, list[str]] = {}
    for storage_document, root in sorted(state.items()):
        if not storage_document.startswith(BUILD_TARGET_PREFIX):
            continue
        name = storage_document[len(BUILD_TARGET_PREFIX) :]
        config = BuildTargetRegistry._parse_tree(root, name=name)
        documents = [
            str(config["document"]),
            *[str(value) for value in config["additional_documents"]],
        ]
        for document in documents:
            references.setdefault(document, []).append(name)
    return references


def validate_build_target_references(state: dict[str, JsonObject]) -> None:
    """Reject an exact state containing a dangling or reserved source binding."""

    for document, target_names in build_target_references(state).items():
        if is_project_metadata_document(document) or document not in state:
            raise ValidationError(
                "INVALID_BUILD_TARGET_DOCUMENT_REFERENCE",
                f"program document {document!r} is required by build targets {target_names!r}",
            )
