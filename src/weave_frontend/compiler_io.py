"""Compatibility alias for :mod:`weave_frontend.compiler.compiler_io`."""

import sys

from .compiler import compiler_io as _implementation

CompilerFileTooLarge = _implementation.CompilerFileTooLarge
read_bounded_bytes = _implementation.read_bounded_bytes
read_bounded_json = _implementation.read_bounded_json
read_bounded_text = _implementation.read_bounded_text
sys.modules[__name__] = _implementation

__all__ = list(_implementation.__all__)
