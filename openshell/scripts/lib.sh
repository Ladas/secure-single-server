#!/usr/bin/env bash
set -euo pipefail
OPENSHELL_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd -- "${OPENSHELL_DIR}/.." && pwd)"
# shellcheck source=../../scripts/common/lib.sh
# shellcheck disable=SC1091
source "${REPO_ROOT}/scripts/common/lib.sh"
# shellcheck source=../configs/images.env
# shellcheck disable=SC1091
source "${OPENSHELL_DIR}/configs/images.env"

render_openshell_template() {  # <template.in> <output> [workload-image]
  local in="$1" out="$2"
  sed \
    -e "s#@@ODH_GATEWAY_IMAGE@@#${ODH_GATEWAY_IMAGE}#g" \
    -e "s#@@ODH_SUPERVISOR_IMAGE@@#${ODH_SUPERVISOR_IMAGE}#g" \
    -e "s#@@ODH_SANDBOX_IMAGE@@#${ODH_SANDBOX_IMAGE}#g" \
    -e "s#@@ODH_CLI_IMAGE@@#${ODH_CLI_IMAGE}#g" \
    -e "s#@@ODH_OPENCODE_IMAGE@@#${3:-${ODH_OPENCODE_IMAGE}}#g" \
    -e "s#@@ODH_OPENCLAW_IMAGE@@#${ODH_OPENCLAW_IMAGE}#g" \
    -e "s#@@ODH_CODEX_IMAGE@@#${ODH_CODEX_IMAGE}#g" \
    "${in}" > "${out}"
  if grep -Eq '@@[A-Z0-9_]+@@' "${out}"; then
    die "unresolved template placeholder in ${in}"
  fi
}
