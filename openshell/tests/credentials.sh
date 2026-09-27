#!/usr/bin/env bash
# Synthetic canaries only. Never print a value, even on failure.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../scripts/harness-lib.sh
# shellcheck disable=SC1091
source "${ROOT}/openshell/scripts/harness-lib.sh"
name="key-canary-$$"
unbound="no-key-$$"
provider="canary-$$"
td="$(mktemp -d)"
cleanup() { harness_destroy "${name}"; harness_destroy "${unbound}"; _os provider delete "${provider}" >/dev/null 2>&1 || true; _os profile delete "${provider}" >/dev/null 2>&1 || true; rm -rf "${td}"; }
trap cleanup EXIT
# Pinned CLI requires explicit provider profiles; it ships no registered defaults.
cat >"${td}/profile.yaml" <<YAML
id: ${provider}
display_name: Synthetic canary
category: inference
credentials:
  - name: api_key
    env_vars: [OPENAI_API_KEY]
    required: true
    auth_style: bearer
    header_name: authorization
endpoints:
  - {host: api.openai.com, port: 443, protocol: rest, access: read-write, enforcement: enforce}
binaries: [/usr/bin/node-26]
YAML
_os profile lint -f "${td}/profile.yaml" >/dev/null
_os profile import -f "${td}/profile.yaml" >/dev/null
export OPENAI_API_KEY=synthetic-openshell-canary-not-a-key
export ANTHROPIC_API_KEY=synthetic-openshell-canary-not-a-key
_os provider create --name "${provider}" --type "${provider}" --credential OPENAI_API_KEY >/dev/null
harness_create "${name}" "${ODH_OPENCODE_IMAGE}" "${ROOT}/openshell/harnesses/opencode/profiles/dev/policy.yaml" "${provider}"
harness_ssh "${name}" 'node -e '\''for(const k of ["OPENAI_API_KEY","ANTHROPIC_API_KEY"]) if((process.env[k]||"").includes("synthetic-openshell-canary")) process.exit(1); console.log("raw provider canaries absent")'\'''
# No binding: inherited SSH caller credentials must remain absent too.
harness_create "${unbound}" "${ODH_OPENCODE_IMAGE}" "${ROOT}/openshell/harnesses/opencode/profiles/dev/policy.yaml"
harness_ssh "${unbound}" 'node -e '\''if(process.env.OPENAI_API_KEY || process.env.ANTHROPIC_API_KEY) process.exit(1); console.log("unbound sandbox has no provider keys")'\'''
unset OPENAI_API_KEY ANTHROPIC_API_KEY
echo 'Credential isolation canaries: OK (does not qualify upstream inference)'
