"""Internal implementation package for Jacquard.

Public applications should import :mod:`weave_jacquard`. The historical
``weave_frontend`` namespace remains internal while stored protocol identifiers
and existing implementation modules retain compatibility.
"""

from .compiler import CompilerBridge
from .errors import (
    ArtifactQuotaExceededError,
    ConflictError,
    DatabaseBusyError,
    NotFoundError,
    ValidationError,
    WeaveFrontendError,
)
from .service import MergeResult
from .source_map import render_with_node_map, smallest_node_for_span
from .verified_workspace import SExpressionWorkspace

__all__ = [
    "ArtifactQuotaExceededError",
    "CompilerBridge",
    "ConflictError",
    "DatabaseBusyError",
    "MergeResult",
    "NotFoundError",
    "SExpressionWorkspace",
    "ValidationError",
    "WeaveFrontendError",
    "render_with_node_map",
    "smallest_node_for_span",
]
