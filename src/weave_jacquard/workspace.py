"""Safe public workspace boundary for Jacquard applications."""

from __future__ import annotations

from typing import NoReturn

from weave_frontend import SExpressionWorkspace as _InternalSExpressionWorkspace


class _UnavailablePublicOperation:
    """Descriptor that removes an internal operation from the public API."""

    def __init__(self, message: str) -> None:
        self.message = message

    def __get__(
        self,
        instance: object | None,
        owner: type[object] | None = None,
    ) -> NoReturn:
        raise AttributeError(self.message)


class SExpressionWorkspace(_InternalSExpressionWorkspace):
    """Supported Jacquard workspace with only auditable branch mutations.

    The internal revision service retains a low-level ``checkout`` primitive for
    controlled migration and recovery code. Exposing it here would allow callers
    to move a branch pointer without optimistic concurrency or immutable audit
    evidence. Public callers should create a historical branch with
    ``create_branch_at_revision`` or publish an immutable revert instead.
    """

    checkout = _UnavailablePublicOperation(
        "direct branch checkout is not part of the public Jacquard API"
    )


__all__ = ["SExpressionWorkspace"]
