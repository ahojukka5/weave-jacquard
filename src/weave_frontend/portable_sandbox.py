"""Backward-compatible name for the canonical portable Bubblewrap sandbox."""

from __future__ import annotations

from .sandbox import BubblewrapSandbox


class PortableBubblewrapSandbox(BubblewrapSandbox):
    """Compatibility alias for :class:`BubblewrapSandbox`.

    The canonical implementation now supports Bubblewrap 0.4.x and newer directly.
    """
