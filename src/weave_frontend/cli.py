"""Small command-line shell around the workspace prototype."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .service import Workspace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="weave-front")
    parser.add_argument("--db", type=Path, default=Path("weave.db"))
    subcommands = parser.add_subparsers(dest="command", required=True)

    init = subcommands.add_parser("init")
    init.add_argument("project")

    render = subcommands.add_parser("render")
    render.add_argument("project")
    render.add_argument("module")
    render.add_argument("--branch", default="main")

    symbols = subcommands.add_parser("symbols")
    symbols.add_argument("project")
    symbols.add_argument("--branch", default="main")

    history = subcommands.add_parser("history")
    history.add_argument("project")
    history.add_argument("--branch", default="main")

    validate = subcommands.add_parser("validate")
    validate.add_argument("project")
    validate.add_argument("--branch", default="main")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    with Workspace(args.db) as workspace:
        if args.command == "init":
            project_id, revision_id = workspace.initialize(args.project)
            print(json.dumps({"project_id": project_id, "revision_id": revision_id}))
        elif args.command == "render":
            print(workspace.render(args.project, args.branch, args.module), end="")
        elif args.command == "symbols":
            print(
                json.dumps(
                    [asdict(item) for item in workspace.find_symbols(args.project, args.branch)],
                    indent=2,
                )
            )
        elif args.command == "history":
            print(json.dumps(workspace.list_history(args.project, args.branch), indent=2))
        elif args.command == "validate":
            workspace.validate(args.project, args.branch)
            print("ok")


if __name__ == "__main__":
    main()
