"""Resource ceilings and identity formats for compiler execution."""

from __future__ import annotations

BUILD_KEY_FORMAT = "weave-build-key-v5"
MAX_COMPILER_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_COMPILER_PROTOCOL_BYTES = 16 * 1024 * 1024
MAX_WIR_BYTES = 64 * 1024 * 1024


__all__ = [
    "BUILD_KEY_FORMAT",
    "MAX_COMPILER_OUTPUT_BYTES",
    "MAX_COMPILER_PROTOCOL_BYTES",
    "MAX_WIR_BYTES",
]
