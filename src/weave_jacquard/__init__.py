"""Jacquard, the agent-native programming environment for Weave."""

from weave_frontend import (
    CompilerBridge,
    ConflictError,
    DatabaseBusyError,
    MergeResult,
    NotFoundError,
    ValidationError,
    WeaveFrontendError,
    render_with_node_map,
    smallest_node_for_span,
)

from .workspace import SExpressionWorkspace

JacquardError = WeaveFrontendError

__all__ = [
    "CompilerBridge",
    "ConflictError",
    "DatabaseBusyError",
    "JacquardError",
    "MergeResult",
    "NotFoundError",
    "SExpressionWorkspace",
    "ValidationError",
    "render_with_node_map",
    "smallest_node_for_span",
]
