"""Compatibility alias for :mod:`weave_frontend.compiler.compiler_artifacts`."""

import sys

from .compiler import compiler_artifacts as _implementation

CompilerArtifactMixin = _implementation.CompilerArtifactMixin
MAX_BUILD_MANIFEST_BYTES = _implementation.MAX_BUILD_MANIFEST_BYTES
sys.modules[__name__] = _implementation

__all__ = ["CompilerArtifactMixin", "MAX_BUILD_MANIFEST_BYTES"]
