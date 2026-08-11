"""Stable public contract values for the merge package boundary."""

from weave_frontend.merges import (
    MAX_VALIDATION_OUTPUT_CHARACTERS,
    MERGE_POLICY_FORMAT,
)


def test_merge_public_contract_exports_stable_policy_and_output_limits() -> None:
    assert MERGE_POLICY_FORMAT == "weave-merge-policy-v1"
    assert MAX_VALIDATION_OUTPUT_CHARACTERS == 8192
