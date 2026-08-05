"""Compatibility alias for :mod:`weave_frontend.compiler.compiler_limits`."""

import sys

from .compiler import compiler_limits as _implementation

BUILD_KEY_FORMAT = _implementation.BUILD_KEY_FORMAT
MAX_COMPILER_OUTPUT_BYTES = _implementation.MAX_COMPILER_OUTPUT_BYTES
MAX_COMPILER_PROTOCOL_BYTES = _implementation.MAX_COMPILER_PROTOCOL_BYTES
MAX_WIR_BYTES = _implementation.MAX_WIR_BYTES
sys.modules[__name__] = _implementation

__all__ = list(_implementation.__all__)
