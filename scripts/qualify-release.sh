#!/usr/bin/env bash
set -euo pipefail

mode="${1:-full}"
requested_out="${2:-local-qualification/$mode}"
root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
previous_evidence="${WEAVE_PREVIOUS_RELEASE_EVIDENCE:-}"
compatibility_policy="${WEAVE_COMPATIBILITY_POLICY:-}"

if [[ -n "$compatibility_policy" && -z "$previous_evidence" ]]; then
  echo "WEAVE_COMPATIBILITY_POLICY requires WEAVE_PREVIOUS_RELEASE_EVIDENCE" >&2
  exit 2
fi

bash "$root_dir/scripts/qualify.sh" "$mode" "$requested_out"

final_out="$(
  python - "$root_dir" "$requested_out" <<'PY'
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
requested = Path(sys.argv[2]).expanduser()
if not requested.is_absolute():
    requested = root / requested
print(requested.resolve())
PY
)"

python "$root_dir/scripts/retain-public-manifests.py" "$final_out"

review_status=0
if [[ -n "$previous_evidence" ]]; then
  review_args=(
    "$previous_evidence"
    "$final_out"
    --output "$final_out/compatibility-review.json"
  )
  if [[ -n "$compatibility_policy" ]]; then
    review_args+=(--policy "$compatibility_policy")
  fi
  set +e
  python -m weave_frontend.release_compatibility "${review_args[@]}"
  review_status=$?
  set -e
fi

python "$root_dir/scripts/qualification.py" checksums "$final_out"

if [[ "$review_status" -eq 3 ]]; then
  echo "release compatibility review is required: $final_out/compatibility-review.json" >&2
  exit 3
fi
if [[ "$review_status" -ne 0 ]]; then
  echo "release compatibility review failed" >&2
  exit "$review_status"
fi
printf 'release manifest evidence retained: %s\n' "$final_out"
