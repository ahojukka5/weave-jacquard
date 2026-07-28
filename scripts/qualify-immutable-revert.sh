#!/usr/bin/env bash
set -euo pipefail

mode="${1:-full}"
out_dir="${2:-}"
root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

case "$mode" in
  focused)
    unified_mode="python"
    default_out="local-qualification/immutable-revert-focused"
    ;;
  full)
    unified_mode="full"
    default_out="local-qualification/immutable-revert-full"
    ;;
  *)
    echo "usage: bash scripts/qualify-immutable-revert.sh [focused|full] [output-dir]" >&2
    exit 2
    ;;
esac

printf '%s\n' \
  "compatibility wrapper: running unified $unified_mode qualification" \
  >&2

exec bash "$root_dir/scripts/qualify.sh" "$unified_mode" "${out_dir:-$default_out}"
