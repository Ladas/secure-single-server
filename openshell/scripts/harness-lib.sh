#!/usr/bin/env bash
set -euo pipefail
_HL_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
# shellcheck source=./lib.sh
source "${_HL_DIR}/lib.sh"

: "${OPENSHELL_BIN:=/usr/local/bin/openshell}"
: "${OPENSHELL_GATEWAY_NAME:=local}"
: "${OPENSHELL_SANDBOX_USER:=sandbox}"
: "${OPENSHELL_SANDBOX_CPU:=2}"
: "${OPENSHELL_SANDBOX_MEMORY:=4Gi}"

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

validate_sandbox_resources() {
  # Reject zero and negative-looking values; OpenShell requires positive
  # cores/millicores and positive byte quantities.
  [[ "${OPENSHELL_SANDBOX_CPU}" =~ ^([1-9][0-9]*([.][0-9]+)?|0[.][0-9]*[1-9][0-9]*|[1-9][0-9]*m)$ ]] \
    || die 'OPENSHELL_SANDBOX_CPU must be positive cores or millicores (for example 2, 0.5, or 500m)'
  [[ "${OPENSHELL_SANDBOX_MEMORY}" =~ ^[1-9][0-9]*(Ki|Mi|Gi|Ti|K|M|G|T|B)?$ ]] \
    || die 'OPENSHELL_SANDBOX_MEMORY must be positive bytes or a quantity (for example 512Mi, 4Gi, or 8G)'
}

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

harness_enable_policy_advisor() {  # <sandbox>
  _os settings set "$1" \
    --key agent_policy_proposals_enabled \
    --value true
}

harness_wait_policy_advisor() {  # <sandbox>
  local name="$1" _
  for _ in $(seq 1 30); do
    if printf '%s\n' \
'const response = await fetch("http://policy.local/v1/policy/current", {signal: AbortSignal.timeout(5000)});' \
'if (response.status !== 200) process.exit(1);' \
      | harness_ssh "${name}" 'node --input-type=module' >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  die "policy advisor did not become ready for sandbox ${name}"
}

# Single-phase create: harness is pre-installed in <image_ref>.
harness_create() {  # <name> <image_ref> <policy_file> [provider] [policy_advisor]
  local name="$1" image="$2" policy="$3" provider="${4:-}" policy_advisor="${5:-no}"
  if [[ -n "${provider}" ]]; then
    [[ "${provider}" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]] || die "invalid provider name"
  fi
  [[ "${policy_advisor}" == yes || "${policy_advisor}" == no ]] \
    || die "invalid policy-advisor value"
  require_command ssh
  [[ -f "${policy}" ]] || die "policy file not found: ${policy}"
  validate_sandbox_resources
  note "Creating sandbox ${name} from ${image##*/}"
  # Keep the array nonempty for Bash 3.2 with nounset enabled.
  local -a create_args=(--detach --no-auto-providers --name "${name}" --from "${image}" --policy "${policy}"
    --cpu "${OPENSHELL_SANDBOX_CPU}" --memory "${OPENSHELL_SANDBOX_MEMORY}")
  if [[ -n "${provider}" ]]; then
    create_args+=(--provider "${provider}")
  fi
  if [[ "${policy_advisor}" == yes ]]; then
    create_args+=(--approval-mode manual)
  fi
  _os sandbox create "${create_args[@]}"
  _wait_ready "${name}"
  if [[ "${policy_advisor}" == yes ]]; then
    harness_enable_policy_advisor "${name}"
    harness_wait_policy_advisor "${name}"
  fi
  note "Sandbox ${name} ready"
}

validate_praxis_port() {
  if [[ ! "${PRAXIS_PORT}" =~ ^[1-9][0-9]{0,4}$ ]] || (( PRAXIS_PORT > 65535 )); then
    die 'PRAXIS_PORT must be an integer from 1 to 65535'
  fi
}
