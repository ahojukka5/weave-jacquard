"""Internal implementation package for Jacquard.

Public applications should import :mod:`weave_jacquard`. The historical
``weave_frontend`` namespace remains internal while stored protocol identifiers
and existing implementation modules retain compatibility.
"""

from .compiler_bridge import CompilerBridge
from .concurrent_workspace import SExpressionWorkspace
from .errors import (
    ConflictError,
    DatabaseBusyError,
    NotFoundError,
    ValidationError,
    WeaveFrontendError,
)
from .service import MergeResult
from .source_map import render_with_node_map, smallest_node_for_span

__all__ = [
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
