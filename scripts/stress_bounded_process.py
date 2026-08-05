"""Extended deterministic stress matrix for bounded subprocess termination."""

from __future__ import annotations

import argparse
import os
import signal
import tempfile
from collections.abc import Callable
from pathlib import Path

from weave_frontend.bounded_process import BoundedProcessResult, run_bounded_process

Check = Callable[[BoundedProcessResult], None]


def _write_script(root: Path, name: str, body: str) -> Path:
    path = root / name
    path.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
    path.chmod(0o755)
    return path


def _assert_timeout(result: BoundedProcessResult) -> None:
    assert result.returncode == -signal.SIGKILL
    assert result.timed_out is True
    assert result.output_limited is False
    assert result.stdout == "timeout stdout"
    assert result.stderr == "timeout stderr"


def _assert_output_limit(result: BoundedProcessResult) -> None:
    assert result.returncode == -signal.SIGKILL
    assert result.timed_out is False
    assert result.output_limited is True
    assert len(result.stdout.encode()) + len(result.stderr.encode()) == 32


def _assert_early_exit(result: BoundedProcessResult) -> None:
    assert result.returncode == 7
    assert result.timed_out is False
    assert result.output_limited is False
    assert result.stdout == "early stdout"
    assert result.stderr == "early stderr"


def _assert_closed_stream_timeout(result: BoundedProcessResult) -> None:
    assert result.returncode == -signal.SIGKILL
    assert result.timed_out is True
    assert result.output_limited is False
    assert result.stdout == ""
    assert result.stderr == ""


def _repeat(
    *,
    name: str,
    script: Path,
    iterations: int,
    timeout_seconds: float,
    max_output_bytes: int,
    check: Check,
) -> None:
    for iteration in range(1, iterations + 1):
        result = run_bounded_process(
            [script],
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )
        try:
            check(result)
        except AssertionError as error:
            raise AssertionError(f"{name} failed at iteration {iteration}: {result!r}") from error
        if iteration % 100 == 0 or iteration == iterations:
            print(f"{name}: {iteration}/{iterations}", flush=True)


def run_stress_matrix(iterations: int) -> None:
    """Run every bounded-process termination scenario repeatedly."""

    if os.name != "posix":
        raise RuntimeError("bounded process stress requires POSIX process groups")
    if iterations <= 0:
        raise ValueError("iterations must be positive")

    with tempfile.TemporaryDirectory(prefix="jacquard-process-stress-") as directory:
        root = Path(directory)
        timeout_script = _write_script(
            root,
            "timeout.sh",
            "printf 'timeout stdout'\nprintf 'timeout stderr' >&2\nwhile :; do :; done\n",
        )
        output_limit_script = _write_script(
            root,
            "output-limit.sh",
            "printf 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'\n"
            "printf 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' >&2\n"
            "while :; do :; done\n",
        )
        early_exit_script = _write_script(
            root,
            "early-exit.sh",
            "printf 'early stdout'\nprintf 'early stderr' >&2\nexit 7\n",
        )
        closed_stream_script = _write_script(
            root,
            "closed-streams.sh",
            "exec 1>&-\nexec 2>&-\nwhile :; do :; done\n",
        )

        _repeat(
            name="timeout",
            script=timeout_script,
            iterations=iterations,
            timeout_seconds=0.1,
            max_output_bytes=128,
            check=_assert_timeout,
        )
        _repeat(
            name="output-limit",
            script=output_limit_script,
            iterations=iterations,
            timeout_seconds=1.0,
            max_output_bytes=32,
            check=_assert_output_limit,
        )
        _repeat(
            name="early-exit",
            script=early_exit_script,
            iterations=iterations,
            timeout_seconds=1.0,
            max_output_bytes=128,
            check=_assert_early_exit,
        )
        _repeat(
            name="simultaneous-stream-closure",
            script=closed_stream_script,
            iterations=iterations,
            timeout_seconds=0.02,
            max_output_bytes=128,
            check=_assert_closed_stream_timeout,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--iterations",
        type=int,
        default=1_000,
        help="iterations to run for each scenario (default: 1000)",
    )
    arguments = parser.parse_args()
    run_stress_matrix(arguments.iterations)
    print(f"bounded process stress passed: {arguments.iterations * 4} invocations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
