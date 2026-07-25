"""Command-line access to revision-pinned native builds."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .build_targets import BuildTargetRegistry
from .compiler_bridge import CompilerBridge
from .sexpr_service import SExpressionWorkspace


def _add_revision_selector(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--branch", default="main")
    parser.add_argument("--revision")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="weave-build")
    parser.add_argument("--db", type=Path, default=Path("weave.db"))
    parser.add_argument("--weavec", type=Path)
    parser.add_argument("--build-root", type=Path)
    subcommands = parser.add_subparsers(dest="command", required=True)

    build = subcommands.add_parser(
        "build",
        help="build an explicit ordered document set from one immutable revision",
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
    _add_revision_selector(build)
    build.add_argument("--target")

    target_set = subcommands.add_parser(
        "target-set",
        help="create or update one revisioned named build target",
    )
    target_set.add_argument("project")
    target_set.add_argument("name")
    target_set.add_argument("document", help="primary source document")
    target_set.add_argument(
        "--source",
        dest="additional_documents",
        action="append",
        default=None,
        help="additional source document; repeat to preserve order",
    )
    target_set.add_argument("--branch", default="main")
    target_set.add_argument("--compiler-target")

    target_list = subcommands.add_parser(
        "target-list",
        help="list named build targets from a branch head or revision",
    )
    target_list.add_argument("project")
    _add_revision_selector(target_list)

    target_get = subcommands.add_parser(
        "target-get",
        help="read one named build target",
    )
    target_get.add_argument("project")
    target_get.add_argument("name")
    _add_revision_selector(target_get)

    target_delete = subcommands.add_parser(
        "target-delete",
        help="delete one named target in a new revision",
    )
    target_delete.add_argument("project")
    target_delete.add_argument("name")
    target_delete.add_argument("--branch", default="main")

    target_build = subcommands.add_parser(
        "target-build",
        help="build one named target from a pinned revision",
    )
    target_build.add_argument("project")
    target_build.add_argument("name")
    _add_revision_selector(target_build)

    source_list = subcommands.add_parser(
        "source-list",
        help="list compiler sources without reserved target metadata",
    )
    source_list.add_argument("project")
    _add_revision_selector(source_list)

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
        targets = BuildTargetRegistry(workspace)
        if args.command == "build":
            result = bridge.build(
                args.project,
                args.document,
                additional_documents=args.additional_documents,
                branch=args.branch,
                revision_id=args.revision,
                target=args.target,
            )
        elif args.command == "target-set":
            result = targets.set(
                args.project,
                args.branch,
                args.name,
                args.document,
                additional_documents=args.additional_documents,
                compiler_target=args.compiler_target,
            )
        elif args.command == "target-list":
            result = targets.list(
                args.project,
                branch=args.branch,
                revision_id=args.revision,
            )
        elif args.command == "target-get":
            result = targets.get(
                args.project,
                args.name,
                branch=args.branch,
                revision_id=args.revision,
            )
        elif args.command == "target-delete":
            result = targets.delete(
                args.project,
                args.branch,
                args.name,
            )
        elif args.command == "target-build":
            result = targets.build(
                bridge,
                args.project,
                args.name,
                branch=args.branch,
                revision_id=args.revision,
            )
        elif args.command == "source-list":
            result = targets.program_documents(
                args.project,
                branch=args.branch,
                revision_id=args.revision,
            )
        else:
            result = bridge.get(args.build_id)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
