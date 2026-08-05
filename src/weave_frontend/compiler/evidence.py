"""Compiler evidence profile validation and capability requirements."""

from __future__ import annotations

from typing import Final

from ..errors import ValidationError

DEFAULT_EVIDENCE_PROFILE: Final = "none"
EVIDENCE_PROFILES: Final = ("none", "minimal", "full")
_EVIDENCE_PROTOCOLS: Final = {
    "none": (),
    "minimal": (
        "weavec-build-manifest-v1",
        "weavec-diagnostics-v1",
        "weavec-compilation-trace-v1",
    ),
    "full": (
        "weavec-build-manifest-v1",
        "weavec-diagnostics-v1",
        "weavec-compilation-trace-v1",
    ),
}


def normalize_evidence_profile(value: str | None) -> str:
    """Return one canonical evidence profile or reject the request."""

    profile = DEFAULT_EVIDENCE_PROFILE if value is None else value
    if not isinstance(profile, str) or profile not in EVIDENCE_PROFILES:
        admitted = ", ".join(EVIDENCE_PROFILES)
        raise ValidationError(
            "INVALID_EVIDENCE_PROFILE",
            f"evidence_profile must be one of: {admitted}",
        )
    return profile


def required_evidence_protocols(profile: str | None) -> tuple[str, ...]:
    """Return compiler protocols required before one profile may build."""

    normalized = normalize_evidence_profile(profile)
    return _EVIDENCE_PROTOCOLS[normalized]


__all__ = [
    "DEFAULT_EVIDENCE_PROFILE",
    "EVIDENCE_PROFILES",
    "normalize_evidence_profile",
]
