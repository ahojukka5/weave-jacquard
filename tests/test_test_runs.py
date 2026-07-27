from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Any

import pytest

from weave_frontend import ValidationError
from weave_frontend.errors import ArtifactIntegrityError
from weave_frontend.sandbox import SandboxLimits, SandboxResult
from weave_frontend.test_runs import TestRunService as _TestRunService


class _Workspace:
    def branch_head(self, project: str, branch: str) -> str:
        assert project == "demo"
        assert branch == "main"
        return "revision-exact"


class _Tests:
    def __init__(self, **overrides: Any) -> None:
        self.definition = {
            "name": "smoke",
            "build_target": "application",
            "arguments": ["--count", "3"],
            "stdin": "input\n",
            "expected_exit_code": 7,
            "expected_stdout": "done\n",
            "expected_stderr": "warning\n",
            "timeout_ms": 2_000,
            "max_memory_bytes": 32 * 1024 * 1024,
            "max_output_bytes": 8_192,
            "max_file_bytes": 4_096,
            "definition_hash": "d" * 64,
            **overrides,
        }
        self.calls: list[tuple[Any, ...]] = []

    def get(
        self,
        project: str,
        name: str,
        *,
        branch: str,
        revision_id: str,
    ) -> dict[str, Any]:
        self.calls.append((project, name, branch, revision_id))
        return dict(self.definition)


class _Targets:
    def get(
        self,
        project: str,
        name: str,
        *,
        branch: str,
        revision_id: str,
    ) -> dict[str, Any]:
        assert (project, name, branch, revision_id) == (
            "demo",
            "application",
            "main",
            "revision-exact",
        )
        return {
            "name": name,
            "document": "main.weave",
            "additional_documents": ["support.weave"],
            "compiler_target": "x86_64-unknown-linux-gnu",
        }


class _Compiler:
    def __init__(self, executable: Path, *, status: str = "succeeded") -> None:
        self.executable = executable
        self.status = status
        self.calls: list[tuple[Any, ...]] = []

    def build(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((args, kwargs))
        executable_hash = hashlib.sha256(self.executable.read_bytes()).hexdigest()
        result: dict[str, Any] = {
            "status": self.status,
            "build_id": "b" * 64,
            "revision_hash": "r" * 64,
            "compiler_sha256": "c" * 64,
        }
        if self.status == "succeeded":
            result["artifacts"] = {"executable": "program"}
            result["artifact_paths"] = {"executable": str(self.executable)}
            result["artifact_sha256"] = {"program": executable_hash}
        return result


class _Sandbox:
    def __init__(
        self,
        result: SandboxResult,
        *,
        available: bool = True,
    ) -> None:
        self.result = result
        self.available = available
        self.calls: list[tuple[Any, ...]] = []

    def capabilities(self) -> dict[str, Any]:
        return {
            "format": "weave-sandbox-capabilities-v1",
            "backend": "test-sandbox",
            "available": self.available,
            "version": "test-sandbox 1",
            "probe_error": None if self.available else "disabled for test",
            "policy": {
                "network": "deny",
                "filesystem": "isolated",
                "seccomp": False,
            },
            "policy_hash": "p" * 64,
        }

    def run(
        self,
        executable: Path,
        arguments: list[str],
        stdin: bytes,
        limits: SandboxLimits,
    ) -> SandboxResult:
        self.calls.append((executable, arguments, stdin, limits))
        return self.result


def _executable(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "program"
    path.write_bytes(b"fake executable")
    path.chmod(0o755)
    return path


def _result(
    *,
    returncode: int | None = 7,
    stdout: bytes = b"done\n",
    stderr: bytes = b"warning\n",
    timed_out: bool = False,
    output_limited: bool = False,
    signal: int | None = None,
) -> SandboxResult:
    return SandboxResult(
        returncode=returncode,
        signal=signal,
        termination_reason=(
            "timeout"
            if timed_out
            else "output_limit"
            if output_limited
            else "signal"
            if signal is not None
            else "exit"
        ),
        timed_out=timed_out,
        output_limited=output_limited,
        duration_ms=12,
        stdout=stdout,
        stderr=stderr,
    )


def _service(
    tmp_path: Path,
    *,
    tests: _Tests | None = None,
    compiler_status: str = "succeeded",
    sandbox: _Sandbox | None = None,
) -> tuple[_TestRunService, _Compiler, _Sandbox]:
    executable = _executable(tmp_path)
    compiler = _Compiler(executable, status=compiler_status)
    resolved_sandbox = sandbox or _Sandbox(_result())
    return (
        _TestRunService(
            _Workspace(),
            _Targets(),
            tests or _Tests(),
            compiler,
            resolved_sandbox,
            run_root=tmp_path / "runs",
        ),
        compiler,
        resolved_sandbox,
    )


def test_passed_run_binds_exact_inputs_and_verifies_outputs(tmp_path: Path) -> None:
    service, compiler, sandbox = _service(tmp_path)

    run = service.run("demo", "smoke", branch="main")
    repeated = service.get(run["run_id"])

    assert run["format"] == "weave-test-run-manifest-v1"
    assert run["status"] == "passed"
    assert run["passed"] is True
    assert run["revision_id"] == "revision-exact"
    assert run["definition_hash"] == "d" * 64
    assert run["build_id"] == "b" * 64
    assert run["compiler_sha256"] == "c" * 64
    assert run["sandbox"]["policy_hash"] == "p" * 64
    assert run["expected"]["exit_code"] == 7
    assert run["observed"]["returncode"] == 7
    assert run["assertions"] == {
        "completed_without_timeout": True,
        "completed_without_output_limit": True,
        "exit_code": True,
        "stdout": True,
        "stderr": True,
    }
    assert repeated["manifest_sha256"] == run["manifest_sha256"]
    assert Path(run["artifact_paths"]["stdout"]).read_bytes() == b"done\n"
    assert Path(run["artifact_paths"]["stderr"]).read_bytes() == b"warning\n"
    assert compiler.calls == [
        (
            ("demo", "main.weave"),
            {
                "additional_documents": ["support.weave"],
                "branch": "main",
                "revision_id": "revision-exact",
                "target": "x86_64-unknown-linux-gnu",
            },
        )
    ]
    _, arguments, stdin, limits = sandbox.calls[0]
    assert arguments == ["--count", "3"]
    assert stdin == b"input\n"
    assert limits.as_dict() == {
        "timeout_ms": 2_000,
        "max_memory_bytes": 32 * 1024 * 1024,
        "max_output_bytes": 8_192,
        "max_file_bytes": 4_096,
    }


def test_failed_assertions_are_retained_as_valid_evidence(tmp_path: Path) -> None:
    sandbox = _Sandbox(_result(returncode=8, stdout=b"wrong\n", stderr=b""))
    service, _, _ = _service(tmp_path, sandbox=sandbox)

    run = service.run(
        "demo",
        "smoke",
        branch="main",
        revision_id="revision-exact",
    )

    assert run["status"] == "failed"
    assert run["passed"] is False
    assert run["assertions"]["completed_without_timeout"] is True
    assert run["assertions"]["exit_code"] is False
    assert run["assertions"]["stdout"] is False
    assert run["assertions"]["stderr"] is False
    assert service.get(run["run_id"])["status"] == "failed"


def test_build_and_sandbox_refusals_publish_no_behavioral_run(tmp_path: Path) -> None:
    build_service, _, _ = _service(tmp_path / "build", compiler_status="failed")
    with pytest.raises(ValidationError) as build_error:
        build_service.run("demo", "smoke")
    assert build_error.value.code == "TEST_BUILD_FAILED"
    assert list((tmp_path / "build" / "runs").iterdir()) == []

    unavailable = _Sandbox(_result(), available=False)
    sandbox_service, _, _ = _service(tmp_path / "sandbox", sandbox=unavailable)
    with pytest.raises(ValidationError) as sandbox_error:
        sandbox_service.run("demo", "smoke")
    assert sandbox_error.value.code == "SANDBOX_UNAVAILABLE"
    assert list((tmp_path / "sandbox" / "runs").iterdir()) == []


def test_output_pages_are_bounded_verified_and_binary_safe(tmp_path: Path) -> None:
    sandbox = _Sandbox(_result(stdout=b"a\xffbc", stderr=b""))
    tests = _Tests(expected_stdout="different")
    service, _, _ = _service(tmp_path, tests=tests, sandbox=sandbox)
    run = service.run("demo", "smoke")

    first = service.output_page(run["run_id"], "stdout", max_bytes=2)
    second = service.output_page(
        run["run_id"],
        "stdout",
        start_byte=first["next_byte"],
        max_bytes=2,
    )

    assert first["returned_bytes"] == 2
    assert first["total_bytes"] == 4
    assert first["eof"] is False
    assert first["next_byte"] == 2
    assert base64.b64decode(first["content_base64"]) == b"a\xff"
    assert first["utf8_text"] is None
    assert second["eof"] is True
    assert second["next_byte"] is None
    assert base64.b64decode(second["content_base64"]) == b"bc"
    assert second["utf8_text"] == "bc"
    assert first["stream_sha256"] == hashlib.sha256(b"a\xffbc").hexdigest()
    assert first["manifest_sha256"] == run["manifest_sha256"]


def test_tampered_run_output_is_rejected(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path)
    run = service.run("demo", "smoke")
    Path(run["artifact_paths"]["stdout"]).write_bytes(b"tampered")

    with pytest.raises(ArtifactIntegrityError, match="stdout artifact hash"):
        service.get(run["run_id"])


@pytest.mark.parametrize(
    ("stream", "start_byte", "max_bytes", "code"),
    [
        ("combined", 0, 10, "INVALID_TEST_RUN_STREAM"),
        ("stdout", -1, 10, "INVALID_TEST_RUN_OUTPUT_PAGE"),
        ("stdout", 0, 0, "INVALID_TEST_RUN_OUTPUT_PAGE"),
        ("stdout", 0, 65_537, "INVALID_TEST_RUN_OUTPUT_PAGE"),
    ],
)
def test_output_page_validation(
    tmp_path: Path,
    stream: str,
    start_byte: int,
    max_bytes: int,
    code: str,
) -> None:
    service, _, _ = _service(tmp_path)
    run = service.run("demo", "smoke")

    with pytest.raises(ValidationError) as raised:
        service.output_page(
            run["run_id"],
            stream,
            start_byte=start_byte,
            max_bytes=max_bytes,
        )
    assert raised.value.code == code
