#!/usr/bin/env bash
set -euo pipefail

mode="${1:-python}"
requested_out="${2:-local-qualification/$mode}"
invocation_dir="$PWD"

case "$mode" in
  python|native|full) ;;
  *)
    echo "usage: bash scripts/qualify.sh [python|native|full] [output-dir]" >&2
    exit 2
    ;;
esac

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root_dir"

case ":${PYTHONPATH:-}:" in
  *":$root_dir/src:"*) ;;
  *) export PYTHONPATH="$root_dir/src${PYTHONPATH:+:$PYTHONPATH}" ;;
esac

required_imports=(mcp pytest pytest_cov)
imports_csv="$(IFS=,; printf '%s' "${required_imports[*]}")"

has_required_imports() {
  python - "$imports_csv" <<'PY' >/dev/null 2>&1
import importlib
import sys

for name in sys.argv[1].split(","):
    importlib.import_module(name)
PY
}

if ! has_required_imports; then
  if [[ -z "${WEAVE_QUALIFICATION_UV_ISOLATED:-}" ]] && command -v uv >/dev/null 2>&1; then
    exec env WEAVE_QUALIFICATION_UV_ISOLATED=1 \
      uv run --isolated --extra dev -- bash "$0" "$@"
  fi
  echo "the qualification Python is missing required modules: ${required_imports[*]}" >&2
  if [[ -n "${WEAVE_QUALIFICATION_UV_ISOLATED:-}" ]]; then
    echo "the isolated uv project environment could not provide the dependencies" >&2
  else
    echo "install the project dependencies with:" >&2
    echo "  python -m pip install -e '.[dev]'" >&2
    echo "or install uv and rerun the qualification script" >&2
  fi
  exit 2
fi

if python -m ruff --version >/dev/null 2>&1; then
  ruff_cmd=(python -m ruff)
elif command -v ruff >/dev/null 2>&1; then
  ruff_cmd=(ruff)
else
  echo "ruff is unavailable in the selected qualification environment" >&2
  exit 2
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "qualification requires a clean tracked worktree" >&2
  git status --short >&2
  exit 2
fi

mapfile -t untracked < <(git ls-files --others --exclude-standard)
if [[ "${#untracked[@]}" -ne 0 ]]; then
  echo "qualification requires no untracked non-ignored files" >&2
  printf '  %s\n' "${untracked[@]}" >&2
  exit 2
fi

final_out="$(
  python scripts/qualification.py resolve-output "$root_dir" "$requested_out"
)"
case "$final_out" in
  "$root_dir"/*)
    relative_out="${final_out#"$root_dir"/}"
    if ! git check-ignore -q -- "$relative_out"; then
      echo "qualification output inside the repository must be ignored: $relative_out" >&2
      exit 2
    fi
    ;;
esac

out_parent="$(dirname "$final_out")"
out_name="$(basename "$final_out")"
mkdir -p "$out_parent"
staging_dir="$(mktemp -d "$out_parent/.${out_name}.tmp.XXXXXX")"
base_temp="$(mktemp -d "${TMPDIR:-/tmp}/jacquard-qualification.XXXXXX")"

cleanup() {
  rm -rf -- "$base_temp"
  if [[ -n "${staging_dir:-}" ]]; then
    rm -rf -- "$staging_dir"
  fi
}
trap cleanup EXIT

out_dir="$staging_dir"
export PYTHONPYCACHEPREFIX="$base_temp/pycache"
export COVERAGE_FILE="$base_temp/.coverage"

compiler_path=""
compiler_sha256=""
compiler_version=""
if [[ "$mode" == "native" || "$mode" == "full" ]]; then
  configured_compiler="${WEAVEC_BIN:-}"
  if [[ -z "$configured_compiler" ]]; then
    echo "mode $mode requires executable WEAVEC_BIN" >&2
    exit 2
  fi
  compiler_path="$(
    python - "$configured_compiler" "$invocation_dir" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1]).expanduser()
if not path.is_absolute():
    path = Path(sys.argv[2]) / path
print(path.resolve())
PY
  )"
  if [[ ! -f "$compiler_path" || ! -x "$compiler_path" ]]; then
    echo "mode $mode requires executable WEAVEC_BIN: $compiler_path" >&2
    exit 2
  fi
  export WEAVEC_BIN="$compiler_path"
  compiler_sha256="$(
    python - "$compiler_path" <<'PY'
import hashlib
import sys
from pathlib import Path

digest = hashlib.sha256()
with Path(sys.argv[1]).open("rb") as stream:
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
print(digest.hexdigest())
PY
  )"
  compiler_version="$(python scripts/qualification.py command-version "$compiler_path")"
fi

if [[ -n "${WEAVE_QUALIFICATION_UV_ISOLATED:-}" ]]; then
  environment_kind="uv-isolated-project-environment"
else
  environment_kind="current-python"
fi

started_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
started_epoch="$(date +%s)"
git_sha="$(git rev-parse HEAD)"
python_version="$(python --version 2>&1)"
python_executable="$(python -c 'import sys; print(sys.executable)')"
ruff_version="$("${ruff_cmd[@]}" --version 2>&1)"

{
  printf 'format=weave-jacquard-qualification-environment-v1\n'
  printf 'started_utc=%s\n' "$started_utc"
  printf 'mode=%s\n' "$mode"
  printf 'git_sha=%s\n' "$git_sha"
  printf 'git_branch=%s\n' "$(git branch --show-current)"
  printf 'repository_root=%s\n' "$root_dir"
  printf 'evidence_directory=%s\n' "$final_out"
  printf 'environment_kind=%s\n' "$environment_kind"
  printf 'python=%s\n' "$python_version"
  printf 'python_executable=%s\n' "$python_executable"
  printf 'pythonpath=%s\n' "$PYTHONPATH"
  printf 'ruff=%s\n' "$ruff_version"
  printf 'ruff_command='
  printf '%q ' "${ruff_cmd[@]}"
  printf '\n'
  printf 'platform=%s\n' "$(uname -a)"
  printf 'weavec_bin=%s\n' "$compiler_path"
  printf 'weavec_sha256=%s\n' "$compiler_sha256"
  printf 'weavec_version=%s\n' "$compiler_version"
} | tee "$out_dir/environment.txt"

python scripts/qualification.py packages > "$out_dir/python-packages.txt"

set -o pipefail
python -m compileall -q src tests scripts/qualification.py 2>&1 \
  | tee "$out_dir/compileall.log"
"${ruff_cmd[@]}" check . 2>&1 | tee "$out_dir/ruff.log"

python - "$out_dir/sandbox-capabilities.json" "$out_dir/sandbox-binaries.json" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

from weave_frontend.sandbox import BubblewrapSandbox

capability_path = Path(sys.argv[1])
binary_path = Path(sys.argv[2])
sandbox = BubblewrapSandbox()
capabilities = sandbox.capabilities()
capability_path.write_text(
    json.dumps(capabilities, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)


def identity(path: Path | None) -> dict[str, object]:
    if path is None:
        return {"path": None, "bytes": None, "sha256": None}
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


binary_path.write_text(
    json.dumps(
        {
            "format": "weave-jacquard-sandbox-binaries-v1",
            "bubblewrap": identity(sandbox.executable),
            "prlimit": identity(sandbox.prlimit),
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
print(json.dumps(capabilities, indent=2, sort_keys=True))
if not capabilities["available"]:
    error = capabilities.get("probe_error") or "strict sandbox is unavailable"
    raise SystemExit(f"mandatory strict sandbox qualification failed: {error}")
PY

pytest_args=(
  -q
  --tb=short
  --strict-markers
  -p no:cacheprovider
  --cov=weave_frontend
  --cov-report=term-missing
  "--cov-report=xml:$out_dir/coverage.xml"
  "--junitxml=$out_dir/pytest-junit.xml"
  --basetemp "$base_temp"
)

case "$mode" in
  python)
    pytest_args+=(-m "not real_e2e")
    ;;
  native)
    pytest_args+=(-m real_e2e tests/e2e)
    ;;
  full)
    ;;
esac

{
  printf 'python -m pytest '
  printf '%q ' "${pytest_args[@]}"
  printf '\n'
} > "$out_dir/pytest-command.txt"

python -m pytest "${pytest_args[@]}" 2>&1 | tee "$out_dir/pytest.log"

python scripts/qualification.py junit \
  "$out_dir/pytest-junit.xml" \
  "$out_dir/junit-summary.json"

python scripts/qualification.py traces \
  "$base_temp" \
  "$out_dir" \
  "$mode" \
  scripts/qualification-traces.json

completed_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
completed_epoch="$(date +%s)"
duration_seconds="$((completed_epoch - started_epoch))"
python scripts/qualification.py complete \
  "$out_dir" \
  "$mode" \
  "$git_sha" \
  "$started_utc" \
  "$completed_utc" \
  "$duration_seconds"

python scripts/qualification.py checksums "$out_dir"

mv -T -n -- "$staging_dir" "$final_out"
if [[ -d "$staging_dir" ]]; then
  echo "qualification output appeared during execution; refusing to overwrite: $final_out" >&2
  exit 2
fi
staging_dir=""
printf 'qualification complete: %s\n' "$final_out"
