#!/usr/bin/env bash
set -euo pipefail
H_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../scripts/harness-lib.sh
# shellcheck disable=SC1091
source "${H_DIR}/../../scripts/harness-lib.sh"
# shellcheck source=../../configs/images.env
# shellcheck disable=SC1091
source "${OPENSHELL_DIR:-${H_DIR}/../..}/configs/images.env"
PROFILE=""; NAME=""; HARNESS_CONFIG_DIR=""; PROVIDER=""
while [[ $# -gt 0 ]]; do
  [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || die "missing value for $1"
  case "$1" in
  --provider) PROVIDER="$2"; shift 2;;
  --profile) PROFILE="$2"; shift 2;;
  --name) NAME="$2"; shift 2;;
  --config) HARNESS_CONFIG_DIR="$2"; shift 2;;
  *) die "unknown arg: $1";;
esac; done
[[ -n "${PROFILE}" ]] || die "usage: create.sh --profile <review|dev|automation|interactive> [--name N] [--config <dir>]"

case "${PROFILE}" in review|dev|automation|interactive) ;; *) die "no such profile: ${PROFILE}" ;; esac
[[ "${NAME:-sandbox}" =~ ^[a-zA-Z0-9][a-zA-Z0-9-]*$ ]] || die "invalid sandbox name"

if [[ -n "${HARNESS_CONFIG_DIR}" ]]; then
  [[ -z "${PROVIDER}" ]] || die "integrated mode cannot attach a direct provider"
  # Integrated openshell-praxis flow: profile + provider config come from
  # <HARNESS_CONFIG_DIR> (e.g. configs/openshell-praxis) instead of this harness dir.
  [[ -d "${HARNESS_CONFIG_DIR}" ]] || die "no such config dir: ${HARNESS_CONFIG_DIR}"
  POLICY_SRC="${HARNESS_CONFIG_DIR}/profiles/${PROFILE}/policy.yaml"
  [[ -f "${POLICY_SRC}" ]] || die "no such profile in config dir: ${POLICY_SRC}"
  PROVIDER_SRC="${HARNESS_CONFIG_DIR}/harness-provider.json.in"
  [[ -f "${PROVIDER_SRC}" ]] || die "provider template not found: ${PROVIDER_SRC}"
  NAME="${NAME:-opencode-${PROFILE}}"
  PRAXIS_PORT="${PRAXIS_PORT:-8080}"
  validate_praxis_port
  : "${OPENSHELL_MODEL_ID:?set OPENSHELL_MODEL_ID to the administrator-approved model id}"
  # Render @@PRAXIS_PORT@@ in the policy (mirrors tests/openshell-praxis/smoke.sh).
  POL="$(mktemp)"; PROV="$(mktemp)"
  # shellcheck disable=SC2329
  # shellcheck disable=SC2317  # invoked via trap, not directly
  cleanup() { rm -f "${POL}" "${PROV}"; }
  trap cleanup EXIT
  sed "s#@@PRAXIS_PORT@@#${PRAXIS_PORT}#g" "${POLICY_SRC}" > "${POL}"
  python3 - "${PROVIDER_SRC}" "${PROV}" "${PRAXIS_PORT}" "${OPENSHELL_MODEL_ID}" <<'RENDER'
import json, sys
src, dest, port, model = sys.argv[1:]
data = json.load(open(src))
provider = data['provider']['praxis']
provider['options']['baseURL'] = f'http://host.openshell.internal:{port}/v1'
provider['models'] = {model: {'name': 'Administrator-approved model'}}
data['model'] = 'praxis/' + model
with open(dest, 'w') as out:
    json.dump(data, out)
RENDER
  harness_create "${NAME}" "${ODH_OPENCODE_IMAGE}" "${POL}"
  # OpenCode reads global provider config from ~/.config/opencode/opencode.json
  # (see https://opencode.ai/docs/config/); push the rendered file there.
  harness_ssh "${NAME}" 'mkdir -p ~/.config/opencode && cat > ~/.config/opencode/opencode.json' < "${PROV}"
  note "Provider config installed at ~/.config/opencode/opencode.json (Praxis loopback :${PRAXIS_PORT}, model ${OPENSHELL_MODEL_ID})"
  note "Connect with: ${H_DIR}/connect.sh --name ${NAME}"
  exit 0
fi

PROFILE_DIR="${H_DIR}/profiles/${PROFILE}"
[[ -d "${PROFILE_DIR}" ]] || die "no such profile: ${PROFILE}"
NAME="${NAME:-opencode-${PROFILE}}"
harness_create "${NAME}" "${ODH_OPENCODE_IMAGE}" "${PROFILE_DIR}/policy.yaml" "${PROVIDER}"
note "Connect with: ${H_DIR}/connect.sh --name ${NAME}"
