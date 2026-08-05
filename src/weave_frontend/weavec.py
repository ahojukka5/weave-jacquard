"""Compatibility alias for :mod:`weave_frontend.compiler.weavec`."""

import sys

from .compiler import weavec as _implementation

WeavecValidator = _implementation.WeavecValidator
sys.modules[__name__] = _implementation

__all__ = ["WeavecValidator"]
