#!/usr/bin/env bash
set -euo pipefail

mode="${1:-full}"

case "$mode" in
  focused|full) ;;
  *)
    echo "usage: bash scripts/qualify-immutable-revert.sh [focused|full] [output-dir]" >&2
    exit 2
    ;;
esac

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root_dir"
export PYTHONPATH="$root_dir/src${PYTHONPATH:+:$PYTHONPATH}"

out_dir="${2:-local-qualification/immutable-revert-$mode}"
base_temp="$out_dir/pytest-tmp"

if [[ -z "$out_dir" || "$out_dir" == "/" || "$out_dir" == "." ]]; then
  echo "refusing unsafe output directory: $out_dir" >&2
  exit 2
fi

required_imports=(mcp pytest)
if [[ "$mode" == "full" ]]; then
  required_imports+=(pytest_cov)
fi

imports_csv="$(IFS=,; printf '%s' "${required_imports[*]}")"
if python - "$imports_csv" <<'PY' >/dev/null 2>&1
import importlib
import sys

for name in sys.argv[1].split(","):
    importlib.import_module(name)
PY
then
  python_cmd=(python)
  environment_kind="current-python"
elif command -v uv >/dev/null 2>&1; then
  python_cmd=(uv run --extra dev python)
  environment_kind="uv-project-environment"
else
  echo "the selected Python is missing required modules: ${required_imports[*]}" >&2
  echo "install the project dependencies with:" >&2
  echo "  python -m pip install -e '.[dev]'" >&2
  echo "or install uv and rerun the qualification script" >&2
  exit 2
fi

if "${python_cmd[@]}" -m ruff --version >/dev/null 2>&1; then
  ruff_cmd=("${python_cmd[@]}" -m ruff)
elif [[ "$environment_kind" == "uv-project-environment" ]]; then
  ruff_cmd=(uv run --extra dev ruff)
elif command -v ruff >/dev/null 2>&1; then
  ruff_cmd=(ruff)
else
  echo "ruff is unavailable in the selected qualification environment" >&2
  echo "install the project development dependencies with:" >&2
  echo "  python -m pip install -e '.[dev]'" >&2
  exit 2
fi

rm -rf "$out_dir"
mkdir -p "$out_dir"

{
  printf 'timestamp_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'git_sha=%s\n' "$(git rev-parse HEAD)"
  printf 'git_branch=%s\n' "$(git branch --show-current)"
  printf 'repository_root=%s\n' "$root_dir"
  printf 'environment_kind=%s\n' "$environment_kind"
  printf 'python=%s\n' "$("${python_cmd[@]}" --version 2>&1)"
  printf 'python_executable=%s\n' "$("${python_cmd[@]}" -c 'import sys; print(sys.executable)')"
  printf 'python_command='
  printf '%q ' "${python_cmd[@]}"
  printf '\n'
  printf 'pythonpath=%s\n' "$PYTHONPATH"
  printf 'ruff=%s\n' "$("${ruff_cmd[@]}" --version 2>&1)"
  printf 'ruff_command='
  printf '%q ' "${ruff_cmd[@]}"
  printf '\n'
  printf 'platform=%s\n' "$(uname -a)"
} | tee "$out_dir/environment.txt"

set -o pipefail
"${python_cmd[@]}" -m compileall -q src tests 2>&1 | tee "$out_dir/compileall.log"
"${ruff_cmd[@]}" check . 2>&1 | tee "$out_dir/ruff.log"

if [[ "$mode" == "focused" ]]; then
  "${python_cmd[@]}" -m pytest -q --tb=short \
    tests/test_revert.py \
    tests/test_build_target_reference_integrity.py \
    tests/test_application.py \
    tests/test_mcp_capabilities.py \
    tests/test_mcp_revert.py \
    tests/e2e/test_real_mcp_revert.py \
    --basetemp "$base_temp" 2>&1 | tee "$out_dir/pytest.log"
else
  "${python_cmd[@]}" -m pytest -q --tb=short \
    --cov=weave_frontend --cov-report=term-missing \
    --basetemp "$base_temp" 2>&1 | tee "$out_dir/pytest.log"
fi

mapfile -t traces < <(find "$base_temp" -name immutable-revert-trace.json -print)
if [[ "${#traces[@]}" -ne 1 ]]; then
  echo "expected exactly one immutable-revert-trace.json, found ${#traces[@]}" \
    | tee "$out_dir/trace-error.log" >&2
  exit 1
fi
cp "${traces[0]}" "$out_dir/immutable-revert-trace.json"

(
  cd "$out_dir"
  sha256sum environment.txt compileall.log ruff.log pytest.log \
    immutable-revert-trace.json > SHA256SUMS
)

printf 'qualification complete: %s\n' "$out_dir"
