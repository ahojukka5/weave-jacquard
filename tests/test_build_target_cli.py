from __future__ import annotations

from weave_frontend.build_cli import build_parser


def test_target_set_preserves_source_order() -> None:
    args = build_parser().parse_args(
        [
            "target-set",
            "demo",
            "app",
            "main.weave",
            "--source",
            "library.weave",
            "--source",
            "platform.weave",
            "--compiler-target",
            "x86_64-unknown-linux-musl",
            "--branch",
            "release",
        ]
    )

    assert args.command == "target-set"
    assert args.project == "demo"
    assert args.name == "app"
    assert args.document == "main.weave"
    assert args.additional_documents == ["library.weave", "platform.weave"]
    assert args.compiler_target == "x86_64-unknown-linux-musl"
    assert args.branch == "release"


def test_target_validate_accepts_exact_revision() -> None:
    args = build_parser().parse_args(
        [
            "target-validate",
            "demo",
            "app",
            "--branch",
            "release",
            "--revision",
            "revision-789",
        ]
    )

    assert args.command == "target-validate"
    assert args.project == "demo"
    assert args.name == "app"
    assert args.branch == "release"
    assert args.revision == "revision-789"


def test_target_build_accepts_exact_revision() -> None:
    args = build_parser().parse_args(
        [
            "target-build",
            "demo",
            "app",
            "--branch",
            "main",
            "--revision",
            "revision-123",
        ]
    )

    assert args.command == "target-build"
    assert args.project == "demo"
    assert args.name == "app"
    assert args.branch == "main"
    assert args.revision == "revision-123"


def test_source_list_has_revision_selector() -> None:
    args = build_parser().parse_args(["source-list", "demo", "--revision", "revision-456"])

    assert args.command == "source-list"
    assert args.project == "demo"
    assert args.branch == "main"
    assert args.revision == "revision-456"
