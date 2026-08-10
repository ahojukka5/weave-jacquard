"""Public boundary for immutable builds, discovery, and evidence inspection."""

from .catalog import MAX_BUILD_CATALOG_ENTRIES, BuildDiscoveryService
from .concurrency import BuildTargetRegistry as ConcurrentBuildTargetRegistry
from .discovery import BUILD_CATALOG_FORMAT, BUILD_LIST_FORMAT, MAX_BUILD_LIST_PAGE_SIZE
from .inspection import MAX_DIAGNOSTIC_PAGE_SIZE, BuildInspectionService

__all__ = [
    "BUILD_CATALOG_FORMAT",
    "BUILD_LIST_FORMAT",
    "BuildDiscoveryService",
    "BuildInspectionService",
    "ConcurrentBuildTargetRegistry",
    "MAX_BUILD_CATALOG_ENTRIES",
    "MAX_BUILD_LIST_PAGE_SIZE",
    "MAX_DIAGNOSTIC_PAGE_SIZE",
]
