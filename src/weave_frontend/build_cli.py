"""Command-line access to revision-pinned native builds and database operations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .build_targets import BuildTargetRegistry
from .compiler_bridge import CompilerBridge
from .database import Database
from .database_backup import (
    DEFAULT_DATABASE_BACKUP_TIMEOUT_SECONDS,
    DatabaseBackupService,
)
from .database_integrity import inspect_database
from .errors import ConflictError, ValidationError, WeaveFrontendError
from .sexpr_service import SExpressionWorkspace
from .target_validation import BuildTargetValidator


def _add_revision_selector(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--branch", default="main")
    parser.add_argument("--revision")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="weave-build")
    parser.add_argument("--db", type=Path, default=Path("weave.db"))
    parser.add_argument("--weavec", type=Path)
    parser.add_argument("--build-root", type=Path)
    parser.add_argument("--backup-root", type=Path)
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

    target_validate = subcommands.add_parser(
        "target-validate",
        help="validate one named target from a pinned revision",
    )
    target_validate.add_argument("project")
    target_validate.add_argument("name")
    _add_revision_selector(target_validate)

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

    subcommands.add_parser(
        "db-check",
        help="inspect database integrity read-only without running migrations",
    )

    database_backup = subcommands.add_parser(
        "db-backup",
        help="create and verify one immutable online SQLite backup",
    )
    database_backup.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_DATABASE_BACKUP_TIMEOUT_SECONDS,
    )

    database_backup_get = subcommands.add_parser(
        "db-backup-get",
        help="read and reverify one immutable database backup",
    )
    database_backup_get.add_argument("backup_id")

    database_restore = subcommands.add_parser(
        "db-restore",
        help="restore a verified backup to one new offline database path",
    )
    database_restore.add_argument("backup_id")
    database_restore.add_argument("destination", type=Path)

    get = subcommands.add_parser("get", help="read a stored build manifest")
    get.add_argument("build_id")
    return parser


def _backup_root(args: argparse.Namespace) -> Path:
    if args.backup_root is not None:
        return args.backup_root
    return args.db.parent / ".weave-database-backups"


def _offline_backup_store(args: argparse.Namespace) -> DatabaseBackupService:
    return DatabaseBackupService(None, backup_root=_backup_root(args))


def _execute(args: argparse.Namespace) -> Any:
    if args.command == "db-check":
        return inspect_database(args.db)
    if args.command == "db-backup":
        with Database(args.db) as database:
            return DatabaseBackupService(
                database,
                backup_root=_backup_root(args),
            ).create(timeout_seconds=args.timeout_seconds)
    if args.command == "db-backup-get":
        return _offline_backup_store(args).get(args.backup_id)
    if args.command == "db-restore":
        return _offline_backup_store(args).restore(
            args.backup_id,
            args.destination,
        )

    with SExpressionWorkspace(args.db, weavec_binary=args.weavec) as workspace:
        targets = BuildTargetRegistry(workspace)
        bridge_instance: CompilerBridge | None = None

        def bridge() -> CompilerBridge:
            nonlocal bridge_instance
            if bridge_instance is None:
                bridge_instance = CompilerBridge(
                    workspace,
                    compiler=args.weavec,
                    build_root=args.build_root,
                )
            return bridge_instance

        if args.command == "build":
            return bridge().build(
                args.project,
                args.document,
                additional_documents=args.additional_documents,
                branch=args.branch,
                revision_id=args.revision,
                target=args.target,
            )
        if args.command == "target-set":
            return targets.set(
                args.project,
                args.branch,
                args.name,
                args.document,
                additional_documents=args.additional_documents,
                compiler_target=args.compiler_target,
            )
        if args.command == "target-list":
            return targets.list(
                args.project,
                branch=args.branch,
                revision_id=args.revision,
            )
        if args.command == "target-get":
            return targets.get(
                args.project,
                args.name,
                branch=args.branch,
                revision_id=args.revision,
            )
        if args.command == "target-delete":
            return targets.delete(
                args.project,
                args.branch,
                args.name,
            )
        if args.command == "target-validate":
            return BuildTargetValidator(targets).validate(
                args.project,
                args.name,
                branch=args.branch,
                revision_id=args.revision,
            )
        if args.command == "target-build":
            return targets.build(
                bridge(),
                args.project,
                args.name,
                branch=args.branch,
                revision_id=args.revision,
            )
        if args.command == "source-list":
            return targets.program_documents(
                args.project,
                branch=args.branch,
                revision_id=args.revision,
            )
        return bridge().get(args.build_id)


def _error_payload(exc: WeaveFrontendError) -> dict[str, Any]:
    if isinstance(exc, ValidationError):
        return exc.as_dict()
    if isinstance(exc, ConflictError):
        return {"code": "MERGE_CONFLICT", "conflicts": exc.conflicts}
    return {"code": type(exc).__name__, "message": str(exc)}


def main() -> None:
    args = build_parser().parse_args()
    try:
        result = _execute(args)
    except WeaveFrontendError as exc:
        print(
            json.dumps(
                {"ok": False, "error": _error_payload(exc)},
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.command == "db-check" and result.get("valid") is not True:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
