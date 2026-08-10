"""Public boundary for immutable build discovery and evidence inspection."""

from .catalog import MAX_BUILD_CATALOG_ENTRIES, BuildDiscoveryService
from .discovery import BUILD_CATALOG_FORMAT, BUILD_LIST_FORMAT, MAX_BUILD_LIST_PAGE_SIZE

__all__ = [
    "BUILD_CATALOG_FORMAT",
    "BUILD_LIST_FORMAT",
    "MAX_BUILD_CATALOG_ENTRIES",
    "MAX_BUILD_LIST_PAGE_SIZE",
    "BuildDiscoveryService",
]
