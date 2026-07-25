"""Jacquard, the agent-native programming environment for Weave."""

from weave_frontend import (
    CompilerBridge,
    ConflictError,
    MergeResult,
    NotFoundError,
    SExpressionWorkspace,
    ValidationError,
    WeaveFrontendError,
    render_with_node_map,
    smallest_node_for_span,
)

JacquardError = WeaveFrontendError

__all__ = [
    "CompilerBridge",
    "ConflictError",
    "JacquardError",
    "MergeResult",
    "NotFoundError",
    "SExpressionWorkspace",
    "ValidationError",
    "render_with_node_map",
    "smallest_node_for_span",
]
