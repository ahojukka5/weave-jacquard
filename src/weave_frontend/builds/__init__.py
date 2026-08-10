"""Public boundary for immutable builds, targets, and evidence inspection."""

from .catalog import MAX_BUILD_CATALOG_ENTRIES, BuildDiscoveryService
from .concurrency import BuildTargetRegistry as ConcurrentBuildTargetRegistry
from .discovery import BUILD_CATALOG_FORMAT, BUILD_LIST_FORMAT, MAX_BUILD_LIST_PAGE_SIZE
from .inspection import MAX_DIAGNOSTIC_PAGE_SIZE, BuildInspectionService
from .metadata import BuildTargetRegistry as MetadataBuildTargetRegistry
from .references import build_target_references, validate_build_target_references
from .targets import BUILD_TARGET_PREFIX, BuildTargetRegistry

__all__ = [
    "BUILD_CATALOG_FORMAT",
    "BUILD_LIST_FORMAT",
    "BUILD_TARGET_PREFIX",
    "BuildDiscoveryService",
    "BuildInspectionService",
    "BuildTargetRegistry",
    "ConcurrentBuildTargetRegistry",
    "MAX_BUILD_CATALOG_ENTRIES",
    "MAX_BUILD_LIST_PAGE_SIZE",
    "MAX_DIAGNOSTIC_PAGE_SIZE",
    "MetadataBuildTargetRegistry",
    "build_target_references",
    "validate_build_target_references",
]
