#!/usr/bin/env bash
set -euo pipefail
_HL_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
# shellcheck source=./lib.sh
source "${_HL_DIR}/lib.sh"

: "${OPENSHELL_BIN:=/usr/local/bin/openshell}"
: "${OPENSHELL_GATEWAY_NAME:=local}"
: "${OPENSHELL_SANDBOX_USER:=sandbox}"

_os() { "${OPENSHELL_BIN}" "$@"; }

# Build the ssh ProxyCommand for a sandbox (native ssh-proxy, name mode).
_proxy_cmd() {  # <sandbox>
  printf '%s ssh-proxy --gateway-name %s --name %s' \
    "${OPENSHELL_BIN}" "${OPENSHELL_GATEWAY_NAME}" "$1"
}

harness_ssh() {  # <sandbox> <cmd...>
  local name="$1"; shift
  # Provider credentials must use explicit gateway bindings, never SSH forwarding.
  ssh -F /dev/null -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o "ProxyCommand=$(_proxy_cmd "${name}")" \
    "${OPENSHELL_SANDBOX_USER}@${name}" "$@"
}

harness_connect_tty() {  # <sandbox> [cmd...]
  local name="$1"; shift || true
  # Provider credentials must use explicit gateway bindings, never SSH forwarding.
  ssh -F /dev/null -t -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o "ProxyCommand=$(_proxy_cmd "${name}")" \
    "${OPENSHELL_SANDBOX_USER}@${name}" "$@"
}

harness_destroy() { _os sandbox delete "$1" >/dev/null 2>&1 || true; }

# Wait until the sandbox reports phase Ready (or fail on Error/timeout).
_wait_ready() {  # <sandbox>
  local name="$1" ph _
  for _ in $(seq 1 40); do
    ph="$(_os sandbox list --output json | python3 -c 'import json,sys; d=json.load(sys.stdin); print(next((s["phase"] for s in d["sandboxes"] if s["name"]==sys.argv[1]), "Missing"))' "${name}")"
    case "${ph}" in
      Ready) return 0;;
      Error) die "sandbox ${name} entered Error phase";;
    esac
    sleep 15
  done
  die "sandbox ${name} did not reach Ready in time"
}

# Single-phase create: harness is pre-installed in <image_ref>.
harness_create() {  # <name> <image_ref> <policy_file>
  local name="$1" image="$2" policy="$3" provider="${4:-}"
  local -a provider_args=()
  if [[ -n "${provider}" ]]; then
    [[ "${provider}" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]] || die "invalid provider name"
    provider_args=(--provider "${provider}")
  fi
  require_command ssh
  [[ -f "${policy}" ]] || die "policy file not found: ${policy}"
  note "Creating sandbox ${name} from ${image##*/}"
  _os sandbox create --detach --no-auto-providers --name "${name}" --from "${image}" --policy "${policy}" "${provider_args[@]}"
  _wait_ready "${name}"
  note "Sandbox ${name} ready"
}

validate_praxis_port() {
  if [[ ! "${PRAXIS_PORT}" =~ ^[1-9][0-9]{0,4}$ ]] || (( PRAXIS_PORT > 65535 )); then
    die 'PRAXIS_PORT must be an integer from 1 to 65535'
  fi
}
