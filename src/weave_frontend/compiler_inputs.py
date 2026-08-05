"""Compatibility alias for :mod:`weave_frontend.compiler.compiler_inputs`."""

import sys

from .compiler import compiler_inputs as _implementation

CompilerInputMixin = _implementation.CompilerInputMixin
MaterializedSource = _implementation.MaterializedSource
RenderedSource = _implementation.RenderedSource
sys.modules[__name__] = _implementation

__all__ = ["CompilerInputMixin", "MaterializedSource", "RenderedSource"]
