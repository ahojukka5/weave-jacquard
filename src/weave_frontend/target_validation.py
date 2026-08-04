"""Validation of revisioned named build targets."""

from __future__ import annotations

from typing import Any

from .build_targets import BuildTargetRegistry
from .source_map import render_with_node_map


class BuildTargetValidator:
    """Validate the exact revision and ordered source set stored in a target."""

    def __init__(self, registry: BuildTargetRegistry) -> None:
        self.registry = registry
        self.workspace = registry.workspace

    def validate(
        self,
        project: str,
        name: str,
        *,
        branch: str = "main",
        revision_id: str | None = None,
    ) -> dict[str, Any]:
        revision = revision_id or self.workspace.branch_head(project, branch)
        config = self.registry.get(
            project,
            name,
            branch=branch,
            revision_id=revision,
        )
        capability_identity: dict[str, Any] | None = None
        capabilities = getattr(self.workspace.validator, "capabilities", None)
        if capabilities is not None:
            capability_registry = capabilities.require(
                command="frontend",
                protocols=("weave-wir-core-v2",),
                target=config["compiler_target"],
            )
            capability_identity = capability_registry["_jacquard_identity"]

        documents = [config["document"], *config["additional_documents"]]
        state = self.workspace._state_at_revision(revision)

        sources: list[tuple[str, str]] = []
        root_node_ids: dict[str, str] = {}
        for document in documents:
            root = state[document]
            source, _ = render_with_node_map(
                root,
                revision_id=revision,
                document=document,
            )
            sources.append((document, source))
            root_node_ids[document] = str(root["id"])

        result = self.workspace.validator.validate_sources(sources)
        result.update(
            {
                "structurally_valid": True,
                "project": project,
                "branch": branch,
                "revision_id": revision,
                "documents": documents,
                "root_node_ids": root_node_ids,
                "build_target": {
                    key: config[key]
                    for key in (
                        "name",
                        "document",
                        "additional_documents",
                        "compiler_target",
                    )
                },
            }
        )
        if capability_identity is not None:
            result["compiler_capabilities"] = capability_identity
        return result
