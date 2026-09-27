#!/usr/bin/env bash
# Requires the single suite-owned gateway; never treats a failed command as proof.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../scripts/harness-lib.sh
# shellcheck disable=SC1091
source "${ROOT}/openshell/scripts/harness-lib.sh"
td="$(mktemp -d)"
DENY="policy-deny-$$"; ALLOW="policy-allow-$$"; server=""
cleanup() {
  harness_destroy "${DENY}"; harness_destroy "${ALLOW}"
  [[ -z "${server}" ]] || kill "${server}" 2>/dev/null || true
  for result in "${td}"/*.json; do [[ ! -f "${result}" ]] || cat "${result}"; done
  rm -rf "${td}"
}
trap cleanup EXIT
fixture_ip="$(ip -4 route get 1.1.1.1 | sed -n 's/.* src \([^ ]*\).*/\1/p')"
[[ -n "${fixture_ip}" ]] || die "cannot determine private fixture address"
python3 "${ROOT}/openshell/tests/controlled-http.py" "${td}/requests" "${fixture_ip}" & server=$!
for ((i=0; i<20; i++)); do
  if curl -s "http://${fixture_ip}:18080" >/dev/null; then break; fi
  sleep 1
done
kill -0 "${server}"
cat >"${td}/deny.yaml" <<'YAML'
version: 1
filesystem_policy: {include_workdir: true, read_only: [/usr, /lib, /lib64, /etc, /proc, /dev/urandom, /opt], read_write: [/sandbox, /tmp, /dev/null, /home]}
landlock: {compatibility: best_effort}
network_policies: {}
YAML
sed '$d' "${td}/deny.yaml" >"${td}/allow.yaml"
cat >>"${td}/allow.yaml" <<'YAML'
network_policies:
  control:
    name: control
    endpoints: [{host: host.containers.internal, port: 18080, protocol: rest, enforcement: enforce, access: read-write}]
    binaries: [{path: /usr/bin/node-26}]
YAML
harness_create "${ALLOW}" "${ODH_OPENCODE_IMAGE}" "${td}/allow.yaml"
harness_create "${DENY}" "${ODH_OPENCODE_IMAGE}" "${td}/deny.yaml"
for name in "${ALLOW}" "${DENY}"; do
  harness_ssh "${name}" 'node --version' >/dev/null
  harness_ssh "${name}" 'cat >/tmp/probe.mjs' <"${ROOT}/openshell/tests/probe.mjs"
done
before="$(wc -l <"${td}/requests")"
harness_ssh "${ALLOW}" 'node /tmp/probe.mjs http://host.containers.internal:18080/' >"${td}/allow.json"
python3 - "${td}/allow.json" <<'PY'
import json,sys
r=json.load(open(sys.argv[1])); assert r['status']==401 and r['body']=='controlled-reachable-401',r
PY
[[ "$(wc -l <"${td}/requests")" -gt "${before}" ]] || die 'positive control did not reach server'
before="$(wc -l <"${td}/requests")"
# Connection failures/timeouts are inconclusive, and fail this test.
harness_ssh "${DENY}" 'node /tmp/probe.mjs http://host.containers.internal:18080/' >"${td}/deny.json"
python3 - "${td}/deny.json" <<'PY'
import json,sys
r=json.load(open(sys.argv[1]))
assert r['status']==403 and 'policy' in r['body'].lower() and 'den' in r['body'].lower(),r
PY
[[ "$(wc -l <"${td}/requests")" == "${before}" ]] || die 'denied request reached controlled server'
echo 'openshell-policy: controlled allow/deny proof OK (401 counts as reachable)'
