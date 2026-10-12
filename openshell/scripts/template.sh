#!/usr/bin/env bash
set -euo pipefail
T_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${T_DIR}/lib.sh"
# Export only validated pin variable names, never the caller's entire environment.
pins="$(python3 "${T_DIR}/workload-templates.py" pins)"
while IFS= read -r pin; do
  [[ "${pin}" =~ ^ODH_[A-Z0-9_]+_IMAGE$ ]] || die 'invalid catalog image variable'
  [[ -n "${!pin:-}" ]] || die "missing image pin: ${pin}"
  export "${pin?}"
done <<<"${pins}"
exec python3 "${T_DIR}/workload-templates.py" "$@"
