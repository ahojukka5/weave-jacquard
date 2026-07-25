"""Command-line access to revision-pinned native builds."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .compiler_bridge import CompilerBridge
from .sexpr_service import SExpressionWorkspace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="weave-build")
    parser.add_argument("--db", type=Path, default=Path("weave.db"))
    parser.add_argument("--weavec", type=Path)
    parser.add_argument("--build-root", type=Path)
    subcommands = parser.add_subparsers(dest="command", required=True)

    build = subcommands.add_parser(
        "build",
        help="build an ordered document set from one immutable revision",
    )
    build.add_argument("project")
    build.add_argument("document", help="primary source document")
    build.add_argument(
        "--source",
        dest="additional_documents",
        action="append",
        default=None,
        help="additional source document; repeat to preserve compiler input order",
    )
    build.add_argument("--branch", default="main")
    build.add_argument("--revision")
    build.add_argument("--target")

    get = subcommands.add_parser("get", help="read a stored build manifest")
    get.add_argument("build_id")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    with SExpressionWorkspace(args.db, weavec_binary=args.weavec) as workspace:
        bridge = CompilerBridge(
            workspace,
            compiler=args.weavec,
            build_root=args.build_root,
        )
        if args.command == "build":
            result = bridge.build(
                args.project,
                args.document,
                additional_documents=args.additional_documents,
                branch=args.branch,
                revision_id=args.revision,
                target=args.target,
            )
        else:
            result = bridge.get(args.build_id)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
