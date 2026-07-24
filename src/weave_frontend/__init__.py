"""Agent-native frontend prototype for Weave."""

from .errors import ConflictError, NotFoundError, ValidationError, WeaveFrontendError
from .model import MergeResult, MutationResult, SymbolSummary
from .service import Workspace
from .sexpr_service import SExpressionWorkspace

__all__ = [
    "ConflictError",
    "MergeResult",
    "MutationResult",
    "NotFoundError",
    "SExpressionWorkspace",
    "SymbolSummary",
    "ValidationError",
    "WeaveFrontendError",
    "Workspace",
]
