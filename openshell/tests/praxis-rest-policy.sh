#!/usr/bin/env bash
# Qualify explicit method/path rules for every shipped Praxis-integrated profile.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../scripts/harness-lib.sh
# shellcheck disable=SC1091
source "${ROOT}/openshell/scripts/harness-lib.sh"

td="$(mktemp -d)"
server=""
cleanup() {
  local result=0
  if [[ -n "${current:-}" ]]; then harness_destroy "${current}" || result=1; fi
  [[ -z "${server}" ]] || kill "${server}" 2>/dev/null || true
  rm -rf "${td}"
  return "${result}"
}
cleanup_status=0
trap 'cleanup_status=$?; if ! cleanup && (( cleanup_status == 0 )); then cleanup_status=1; fi; exit "$cleanup_status"' EXIT

python3 "${ROOT}/openshell/tests/controlled-http.py" "${td}/requests" 0.0.0.0 & server=$!
server_ready=false
for _ in $(seq 1 30); do
  if curl --silent http://127.0.0.1:18080/v1/models >/dev/null; then server_ready=true; break; fi
  kill -0 "${server}" 2>/dev/null
  sleep 1
done
[[ "${server_ready}" == true ]] || die "controlled HTTP fixture did not become ready"

profiles=(
  "review|${ODH_OPENCODE_IMAGE}|${ROOT}/configs/openshell-praxis/profiles/review/policy.yaml"
  "dev|${ODH_OPENCODE_IMAGE}|${ROOT}/configs/openshell-praxis/profiles/dev/policy.yaml"
  "automation|${ODH_OPENCODE_IMAGE}|${ROOT}/configs/openshell-praxis/profiles/automation/policy.yaml"
  "interactive|${ODH_OPENCODE_IMAGE}|${ROOT}/configs/openshell-praxis/profiles/interactive/policy.yaml"
  "openclaw|${ODH_OPENCLAW_IMAGE}|${ROOT}/configs/openshell-praxis/openclaw/profiles/dev/policy.yaml"
  "vllm-opencode|${ODH_OPENCODE_IMAGE}|${ROOT}/configs/vllm/harness/profiles/dev/policy.yaml"
  "vllm-openclaw|${ODH_OPENCLAW_IMAGE}|${ROOT}/configs/vllm/openclaw/profiles/dev/policy.yaml"
)

for profile in "${profiles[@]}"; do
  IFS='|' read -r label image source <<<"${profile}"
  current="praxis-rest-$$"
  policy="${td}/${label}.yaml"
  sed -e 's#@@PRAXIS_PORT@@#18080#g' -e 's#@@PRAXIS_API_PREFIX@@##g' \
    "${source}" >"${policy}"
  harness_create "${current}" "${image}" "${policy}"
  harness_ssh "${current}" 'cat >/tmp/probe.mjs' <"${ROOT}/openshell/tests/probe.mjs"

  before="$(wc -l <"${td}/requests")"
  harness_ssh "${current}" 'node /tmp/probe.mjs http://host.openshell.internal:18080/v1/models GET' \
    >"${td}/allowed.json"
  python3 - "${td}/allowed.json" <<'PY'
import json, sys
result = json.load(open(sys.argv[1]))
assert result == {'kind': 'http', 'status': 401, 'body': 'controlled-reachable-401'}, result
PY
  [[ "$(wc -l <"${td}/requests")" -gt "${before}" ]] || die "${label}: allowed request did not reach fixture"

  for request in 'DELETE /v1/models' 'POST /v1/not-allowed'; do
    method="${request%% *}"
    path="${request#* }"
    before="$(wc -l <"${td}/requests")"
    harness_ssh "${current}" \
      "node /tmp/probe.mjs http://host.openshell.internal:18080${path} ${method}" \
      >"${td}/denied.json"
    python3 - "${td}/denied.json" <<'PY'
import json, sys
result = json.load(open(sys.argv[1]))
assert result == {'kind': 'transport-error', 'code': 'EACCES'}, result
PY
    [[ "$(wc -l <"${td}/requests")" == "${before}" ]] || die "${label}: forbidden request reached fixture"
  done

  harness_destroy "${current}"
  current=""
  echo "Praxis REST policy: ${label} allow/deny checks passed"
done
