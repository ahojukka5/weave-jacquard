"""Regression coverage for the package-owned project merge catalog contract."""

from __future__ import annotations

import inspect

from weave_frontend import project_merge_catalog as root_catalog
from weave_frontend.merges import (
    PROJECT_MERGE_CATALOG_FORMAT,
    ProjectMergeCatalogService,
)


def test_project_merge_catalog_public_boundary_preserves_root_contract() -> None:
    assert PROJECT_MERGE_CATALOG_FORMAT == root_catalog.PROJECT_MERGE_CATALOG_FORMAT
    for method in ("capture", "members"):
        package_signature = inspect.signature(getattr(ProjectMergeCatalogService, method))
        root_signature = inspect.signature(
            getattr(root_catalog.ProjectMergeCatalogService, method)
        )
        assert package_signature == root_signature
