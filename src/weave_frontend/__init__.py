"""Agent-native frontend and revision build environment for Weave."""

from .compiler_bridge import CompilerBridge
from .errors import ConflictError, NotFoundError, ValidationError, WeaveFrontendError
from .model import MergeResult, MutationResult, SymbolSummary
from .service import Workspace
from .sexpr_service import SExpressionWorkspace
from .source_map import render_with_node_map, smallest_node_for_span

__all__ = [
    "CompilerBridge",
    "ConflictError",
    "MergeResult",
    "MutationResult",
    "NotFoundError",
    "SExpressionWorkspace",
    "SymbolSummary",
    "ValidationError",
    "WeaveFrontendError",
    "Workspace",
    "render_with_node_map",
    "smallest_node_for_span",
]
