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
case ":${PYTHONPATH:-}:" in
  *":$root_dir/src:"*) ;;
  *) export PYTHONPATH="$root_dir/src${PYTHONPATH:+:$PYTHONPATH}" ;;
esac

required_imports=(mcp pytest)
if [[ "$mode" == "full" ]]; then
  required_imports+=(pytest_cov)
fi
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

if [[ -n "${WEAVE_QUALIFICATION_UV_ISOLATED:-}" ]]; then
  environment_kind="uv-isolated-project-environment"
else
  environment_kind="current-python"
fi

if python -m ruff --version >/dev/null 2>&1; then
  ruff_cmd=(python -m ruff)
elif command -v ruff >/dev/null 2>&1; then
  ruff_cmd=(ruff)
else
  echo "ruff is unavailable in the selected qualification environment" >&2
  echo "install the project development dependencies with:" >&2
  echo "  python -m pip install -e '.[dev]'" >&2
  exit 2
fi

out_dir="${2:-local-qualification/immutable-revert-$mode}"
base_temp="$out_dir/pytest-tmp"

if [[ -z "$out_dir" || "$out_dir" == "/" || "$out_dir" == "." ]]; then
  echo "refusing unsafe output directory: $out_dir" >&2
  exit 2
fi

python_version="$(python --version 2>&1)"
python_executable="$(python -c 'import sys; print(sys.executable)')"
ruff_version="$("${ruff_cmd[@]}" --version 2>&1)"

rm -rf "$out_dir"
mkdir -p "$out_dir"

{
  printf 'timestamp_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'git_sha=%s\n' "$(git rev-parse HEAD)"
  printf 'git_branch=%s\n' "$(git branch --show-current)"
  printf 'repository_root=%s\n' "$root_dir"
  printf 'environment_kind=%s\n' "$environment_kind"
  printf 'python=%s\n' "$python_version"
  printf 'python_executable=%s\n' "$python_executable"
  printf 'pythonpath=%s\n' "$PYTHONPATH"
  printf 'ruff=%s\n' "$ruff_version"
  printf 'ruff_command='
  printf '%q ' "${ruff_cmd[@]}"
  printf '\n'
  printf 'platform=%s\n' "$(uname -a)"
} | tee "$out_dir/environment.txt"

set -o pipefail
python -m compileall -q src tests 2>&1 | tee "$out_dir/compileall.log"
"${ruff_cmd[@]}" check . 2>&1 | tee "$out_dir/ruff.log"

if [[ "$mode" == "focused" ]]; then
  python -m pytest -q --tb=short \
    tests/test_revert.py \
    tests/test_build_target_reference_integrity.py \
    tests/test_portable_sandbox.py \
    tests/test_sexpr_context.py \
    tests/test_application.py \
    tests/test_mcp_capabilities.py \
    tests/test_mcp_revert.py \
    tests/e2e/test_real_mcp_revert.py \
    --basetemp "$base_temp" 2>&1 | tee "$out_dir/pytest.log"
else
  python -m pytest -q --tb=short \
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
