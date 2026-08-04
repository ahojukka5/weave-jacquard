from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_retention_lifecycle_runbook_covers_operator_and_recovery_contracts() -> None:
    document = (ROOT / "docs/artifact-retention-lifecycle.md").read_text(
        encoding="utf-8"
    )

    for command in (
        "weave-artifact-reconcile",
        "weave-artifact-retention-plan",
        "weave-artifact-quarantine",
        "weave-artifact-quarantine-verify",
        "weave-artifact-quarantine-restore",
        "weave-artifact-quarantine-delete",
    ):
        assert command in document
    for phrase in (
        "Holding period not met",
        "Interrupted quarantine",
        "Interrupted restore",
        "Interrupted permanent deletion",
        "Partial delete batch",
        "no-follow behavior",
        "retained_logical_bytes",
        "quarantined_logical_bytes",
        "Closes #<issue>",
        "When CI is red, the work is unfinished",
    ):
        assert phrase in document
