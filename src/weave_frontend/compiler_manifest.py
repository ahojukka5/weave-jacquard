"""Compatibility alias for :mod:`weave_frontend.compiler.compiler_manifest`."""

import sys

from .compiler import compiler_manifest as _implementation

COMPILER_MANIFEST_FORMAT = _implementation.COMPILER_MANIFEST_FORMAT
validate_compiler_manifest = _implementation.validate_compiler_manifest
sys.modules[__name__] = _implementation

__all__ = ["COMPILER_MANIFEST_FORMAT", "validate_compiler_manifest"]
