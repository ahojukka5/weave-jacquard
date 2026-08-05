"""Compatibility alias for :mod:`weave_frontend.compiler.compiler_bridge`."""

import sys

from .compiler import compiler_bridge as _implementation

CompilerBridge = _implementation.CompilerBridge
sys.modules[__name__] = _implementation

__all__ = ["CompilerBridge"]
