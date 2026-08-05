"""Compatibility alias for :mod:`weave_frontend.compiler.compiler_capabilities`."""

import sys

from .compiler import compiler_capabilities as _implementation

CAPABILITIES_FORMAT = _implementation.CAPABILITIES_FORMAT
CAPABILITIES_SCHEMA_ID = _implementation.CAPABILITIES_SCHEMA_ID
CAPABILITIES_SCHEMA_VERSION = _implementation.CAPABILITIES_SCHEMA_VERSION
CAPABILITIES_TIMEOUT_SECONDS = _implementation.CAPABILITIES_TIMEOUT_SECONDS
MAX_CAPABILITIES_BYTES = _implementation.MAX_CAPABILITIES_BYTES
CapabilityAwareWeavecValidator = _implementation.CapabilityAwareWeavecValidator
CapabilityGrammarIndex = _implementation.CapabilityGrammarIndex
WeavecCapabilities = _implementation.WeavecCapabilities
sys.modules[__name__] = _implementation

__all__ = list(_implementation.__all__)
