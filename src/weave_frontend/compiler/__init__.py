"""Public compiler integration boundary."""

from .compiler_bridge import CompilerBridge
from .compiler_capabilities import (
    CAPABILITIES_FORMAT,
    CAPABILITIES_SCHEMA_ID,
    CAPABILITIES_SCHEMA_VERSION,
    CAPABILITIES_TIMEOUT_SECONDS,
    MAX_CAPABILITIES_BYTES,
    CapabilityAwareWeavecValidator,
    CapabilityGrammarIndex,
    WeavecCapabilities,
)
from .compiler_diagnostics import (
    BUILD_DIAGNOSTICS_FORMAT,
    COMPILER_DIAGNOSTICS_FORMAT,
    collect_build_diagnostics,
)
from .compiler_inputs import MaterializedSource, RenderedSource
from .compiler_io import (
    CompilerFileTooLarge,
    read_bounded_bytes,
    read_bounded_json,
    read_bounded_text,
)
from .compiler_limits import (
    BUILD_KEY_FORMAT,
    MAX_COMPILER_OUTPUT_BYTES,
    MAX_COMPILER_PROTOCOL_BYTES,
    MAX_WIR_BYTES,
)
from .compiler_manifest import COMPILER_MANIFEST_FORMAT, validate_compiler_manifest
from .weavec import WeavecValidator

__all__ = [
    "BUILD_DIAGNOSTICS_FORMAT",
    "BUILD_KEY_FORMAT",
    "CAPABILITIES_FORMAT",
    "CAPABILITIES_SCHEMA_ID",
    "CAPABILITIES_SCHEMA_VERSION",
    "CAPABILITIES_TIMEOUT_SECONDS",
    "COMPILER_DIAGNOSTICS_FORMAT",
    "COMPILER_MANIFEST_FORMAT",
    "MAX_CAPABILITIES_BYTES",
    "MAX_COMPILER_OUTPUT_BYTES",
    "MAX_COMPILER_PROTOCOL_BYTES",
    "MAX_WIR_BYTES",
    "CapabilityAwareWeavecValidator",
    "CapabilityGrammarIndex",
    "CompilerBridge",
    "CompilerFileTooLarge",
    "MaterializedSource",
    "RenderedSource",
    "WeavecCapabilities",
    "WeavecValidator",
    "collect_build_diagnostics",
    "read_bounded_bytes",
    "read_bounded_json",
    "read_bounded_text",
    "validate_compiler_manifest",
]
