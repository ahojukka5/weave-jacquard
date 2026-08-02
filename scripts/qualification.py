#!/usr/bin/env python3
"""Standard-library helpers for deterministic local qualification evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import selectors
import shutil
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from contextlib import suppress
from pathlib import Path
from typing import Any

TRACE_CONTRACT_FORMAT = "weave-jacquard-qualification-traces-v1"
TRACE_INDEX_FORMAT = "weave-jacquard-qualification-trace-index-v1"
COMPLETION_FORMAT = "weave-jacquard-qualification-complete-v1"
MAX_TRACE_FILES = 512
MAX_TRACE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_TRACE_BYTES = 128 * 1024 * 1024
MAX_VERSION_OUTPUT_BYTES = 4096


class QualificationError(RuntimeError):
    """Raised when qualification evidence cannot be admitted."""


def resolve_output(repository_root: Path, requested: str) -> Path:
    """Resolve one new evidence directory without deleting existing content."""

    if not requested or "\x00" in requested or "\n" in requested or "\r" in requested:
        raise QualificationError("output directory must be a non-empty single-line path")
    root = repository_root.resolve()
    candidate = Path(requested).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    if resolved == Path(resolved.anchor) or resolved == root:
        raise QualificationError(f"refusing unsafe output directory: {resolved}")
    if resolved.exists() or resolved.is_symlink():
        raise QualificationError(
            f"output directory already exists; qualification never deletes it: {resolved}"
        )
    return resolved


def package_inventory() -> list[str]:
    """Return a stable installed-distribution inventory without requiring pip."""

    entries = {
        f"{distribution.metadata.get('Name') or distribution.name}"
        f"=={distribution.version}"
        for distribution in importlib.metadata.distributions()
    }
    return sorted(entries, key=str.casefold)


def command_version(executable: Path) -> str:
    """Return bounded `--version` output for one required executable."""

    returncode, output, timed_out, output_limited = _run_bounded_command(
        [str(executable), "--version"],
        timeout_seconds=10,
        max_output_bytes=MAX_VERSION_OUTPUT_BYTES,
    )
    text = output.decode("utf-8", errors="replace").strip()
    if timed_out:
        raise QualificationError("compiler --version timed out after 10 seconds")
    if output_limited:
        raise QualificationError(
            f"compiler version output exceeds {MAX_VERSION_OUTPUT_BYTES} bytes"
        )
    if returncode != 0:
        raise QualificationError(
            f"compiler --version exited {returncode}: {text or 'no output'}"
        )
    if not text:
        raise QualificationError("compiler --version returned no identity")
    return " ".join(text.splitlines())


def summarize_junit(source: Path, destination: Path) -> dict[str, int]:
    """Write and validate one aggregate JUnit summary."""

    root = ET.parse(source).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall(".//testsuite"))
    if not suites:
        raise QualificationError("JUnit evidence contains no test suites")
    summary = {
        key: sum(int(suite.attrib.get(key, "0")) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    destination.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if summary["failures"] or summary["errors"]:
        raise QualificationError("JUnit evidence contains failed or errored tests")
    if summary["skipped"]:
        raise QualificationError(
            f"qualification rejects unexpected skips: {summary['skipped']} test(s) skipped"
        )
    return summary


def collect_traces(
    base: Path,
    out: Path,
    mode: str,
    contract_path: Path,
) -> dict[str, Any]:
    """Validate, bound, retain, and index qualification traces."""

    contract_bytes = _read_bounded(contract_path, MAX_TRACE_BYTES)
    try:
        contract = json.loads(contract_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"invalid qualification trace contract: {exc}") from exc
    protocol, native = _validate_trace_contract(contract)

    required: list[str] = []
    if mode in {"python", "full"}:
        required.extend(protocol)
    if mode in {"native", "full"}:
        required.extend(native)
    if mode not in {"python", "native", "full"}:
        raise QualificationError(f"unsupported qualification mode: {mode}")

    discovered = sorted(
        (
            path
            for path in base.rglob("*")
            if path.is_file()
            and (path.name.endswith("-trace.json") or path.name == "qualification-summary.json")
        ),
        key=lambda path: path.relative_to(base).as_posix(),
    )
    if len(discovered) > MAX_TRACE_FILES:
        raise QualificationError(
            f"qualification produced {len(discovered)} traces; limit is {MAX_TRACE_FILES}"
        )

    by_name: dict[str, list[Path]] = {}
    total_bytes = 0
    sizes: dict[Path, int] = {}
    for path in discovered:
        if path.is_symlink():
            raise QualificationError(f"qualification trace must not be a symlink: {path}")
        size = path.stat().st_size
        if size > MAX_TRACE_BYTES:
            raise QualificationError(
                f"qualification trace {path.name} is {size} bytes; "
                f"limit is {MAX_TRACE_BYTES}"
            )
        total_bytes += size
        if total_bytes > MAX_TOTAL_TRACE_BYTES:
            raise QualificationError(
                f"qualification traces exceed total limit {MAX_TOTAL_TRACE_BYTES} bytes"
            )
        sizes[path] = size
        by_name.setdefault(path.name, []).append(path)

    errors = []
    for name in required:
        count = len(by_name.get(name, []))
        if count != 1:
            errors.append(f"expected exactly one {name}, found {count}")
    if mode in {"native", "full"} and not by_name.get("qualification-summary.json"):
        errors.append("expected at least one native qualification-summary.json")
    if errors:
        raise QualificationError("\n".join(errors))

    retained_contract = out / "qualification-traces.json"
    retained_contract.write_bytes(contract_bytes)
    trace_root = out / "traces"
    entries = []
    for source in discovered:
        relative = source.relative_to(base)
        destination = trace_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        entries.append(
            {
                "path": destination.relative_to(out).as_posix(),
                "basename": destination.name,
                "bytes": sizes[source],
                "sha256": _sha256_file(destination),
                "required": destination.name in required,
            }
        )

    index = {
        "format": TRACE_INDEX_FORMAT,
        "mode": mode,
        "contract_path": retained_contract.name,
        "contract_sha256": hashlib.sha256(contract_bytes).hexdigest(),
        "required_basenames": required,
        "trace_count": len(entries),
        "trace_bytes": total_bytes,
        "limits": {
            "max_trace_files": MAX_TRACE_FILES,
            "max_trace_bytes": MAX_TRACE_BYTES,
            "max_total_trace_bytes": MAX_TOTAL_TRACE_BYTES,
        },
        "traces": entries,
    }
    (out / "trace-index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return index


def write_checksums(out: Path) -> None:
    """Write stable SHA-256 evidence for every retained file except the index itself."""

    checksum_path = out / "SHA256SUMS"
    lines = []
    for path in sorted(
        (path for path in out.rglob("*") if path.is_file() and path != checksum_path),
        key=lambda path: path.relative_to(out).as_posix(),
    ):
        if path.is_symlink():
            raise QualificationError(f"evidence file must not be a symlink: {path}")
        lines.append(f"{_sha256_file(path)}  {path.relative_to(out).as_posix()}")
    checksum_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_completion(
    out: Path,
    *,
    mode: str,
    git_sha: str,
    started_utc: str,
    completed_utc: str,
    duration_seconds: int,
) -> None:
    """Write the success marker immediately before final checksums."""

    payload = {
        "format": COMPLETION_FORMAT,
        "status": "passed",
        "mode": mode,
        "git_sha": git_sha,
        "started_utc": started_utc,
        "completed_utc": completed_utc,
        "duration_seconds": duration_seconds,
    }
    (out / "qualification-complete.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _run_bounded_command(
    command: list[str],
    *,
    timeout_seconds: float,
    max_output_bytes: int,
) -> tuple[int | None, bytes, bool, bool]:
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as exc:
        raise QualificationError(f"cannot launch {' '.join(command)}: {exc}") from exc
    assert process.stdout is not None
    os.set_blocking(process.stdout.fileno(), False)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    output = bytearray()
    deadline = time.monotonic() + timeout_seconds
    timed_out = False
    output_limited = False
    try:
        while selector.get_map() or process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                _kill_process_group(process)
                break
            if not selector.get_map():
                with suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=min(remaining, 0.1))
                continue
            events = selector.select(timeout=min(remaining, 0.1))
            if not events and process.poll() is not None:
                events = [
                    (key, selectors.EVENT_READ)
                    for key in list(selector.get_map().values())
                ]
            for key, _ in events:
                try:
                    chunk = os.read(key.fileobj.fileno(), 65_536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                capacity = max_output_bytes - len(output)
                if capacity <= 0:
                    output_limited = True
                    _kill_process_group(process)
                    break
                output.extend(chunk[:capacity])
                if len(chunk) > capacity:
                    output_limited = True
                    _kill_process_group(process)
                    break
            if timed_out or output_limited:
                break
    finally:
        selector.close()
        process.stdout.close()

    try:
        returncode = process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        _kill_process_group(process)
        returncode = process.wait(timeout=1)
    finally:
        _kill_process_group(process)
    if timed_out or output_limited:
        returncode = None
    return returncode, bytes(output), timed_out, output_limited


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    if process.poll() is None:
        with suppress(ProcessLookupError):
            process.kill()


def _validate_trace_contract(contract: Any) -> tuple[list[str], list[str]]:
    if not isinstance(contract, dict) or set(contract) != {"format", "protocol", "native"}:
        raise QualificationError("qualification trace contract has invalid fields")
    if contract.get("format") != TRACE_CONTRACT_FORMAT:
        raise QualificationError("qualification trace contract has an unsupported format")

    groups: list[list[str]] = []
    for key in ("protocol", "native"):
        value = contract.get(key)
        if not isinstance(value, list) or not value:
            raise QualificationError(f"qualification trace contract {key} must be non-empty")
        if any(
            not isinstance(name, str)
            or not name
            or Path(name).name != name
            or "\\" in name
            or not name.endswith("-trace.json")
            for name in value
        ):
            raise QualificationError(
                f"qualification trace contract {key} contains an invalid basename"
            )
        groups.append(value)
    combined = [*groups[0], *groups[1]]
    if len(combined) != len(set(combined)):
        raise QualificationError("qualification trace basenames must be globally unique")
    return groups[0], groups[1]


def _read_bounded(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise QualificationError(f"{path} exceeds {limit} bytes")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve = subparsers.add_parser("resolve-output")
    resolve.add_argument("repository_root", type=Path)
    resolve.add_argument("requested")

    subparsers.add_parser("packages")

    version = subparsers.add_parser("command-version")
    version.add_argument("executable", type=Path)

    junit = subparsers.add_parser("junit")
    junit.add_argument("source", type=Path)
    junit.add_argument("destination", type=Path)

    traces = subparsers.add_parser("traces")
    traces.add_argument("base", type=Path)
    traces.add_argument("out", type=Path)
    traces.add_argument("mode")
    traces.add_argument("contract", type=Path)

    checksums = subparsers.add_parser("checksums")
    checksums.add_argument("out", type=Path)

    complete = subparsers.add_parser("complete")
    complete.add_argument("out", type=Path)
    complete.add_argument("mode")
    complete.add_argument("git_sha")
    complete.add_argument("started_utc")
    complete.add_argument("completed_utc")
    complete.add_argument("duration_seconds", type=int)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "resolve-output":
            print(resolve_output(args.repository_root, args.requested))
        elif args.command == "packages":
            print("\n".join(package_inventory()))
        elif args.command == "command-version":
            print(command_version(args.executable))
        elif args.command == "junit":
            summarize_junit(args.source, args.destination)
        elif args.command == "traces":
            collect_traces(args.base, args.out, args.mode, args.contract)
        elif args.command == "checksums":
            write_checksums(args.out)
        elif args.command == "complete":
            write_completion(
                args.out,
                mode=args.mode,
                git_sha=args.git_sha,
                started_utc=args.started_utc,
                completed_utc=args.completed_utc,
                duration_seconds=args.duration_seconds,
            )
        else:  # pragma: no cover
            raise QualificationError(f"unsupported command: {args.command}")
    except (QualificationError, OSError, ET.ParseError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
