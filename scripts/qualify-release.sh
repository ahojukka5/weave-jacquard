#!/usr/bin/env bash
set -euo pipefail

mode="${1:-full}"
requested_out="${2:-local-qualification/$mode}"
root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

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
python "$root_dir/scripts/qualification.py" checksums "$final_out"
printf 'release manifest evidence retained: %s\n' "$final_out"
