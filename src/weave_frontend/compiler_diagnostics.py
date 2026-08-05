"""Compatibility alias for :mod:`weave_frontend.compiler.compiler_diagnostics`."""

import sys

from .compiler import compiler_diagnostics as _implementation

BUILD_DIAGNOSTICS_FORMAT = _implementation.BUILD_DIAGNOSTICS_FORMAT
COMPILER_DIAGNOSTICS_FORMAT = _implementation.COMPILER_DIAGNOSTICS_FORMAT
SPAN_ORIGINS = _implementation.SPAN_ORIGINS
collect_build_diagnostics = _implementation.collect_build_diagnostics
sys.modules[__name__] = _implementation

__all__ = [
    "BUILD_DIAGNOSTICS_FORMAT",
    "COMPILER_DIAGNOSTICS_FORMAT",
    "SPAN_ORIGINS",
    "collect_build_diagnostics",
]
