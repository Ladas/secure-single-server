#!/usr/bin/env bash
# Explicit runtime qualification for operator-approved, instance-local grants.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../scripts/harness-lib.sh
# shellcheck disable=SC1091
source "${ROOT}/openshell/scripts/harness-lib.sh"
# shellcheck source=../configs/images.env
# shellcheck disable=SC1091
source "${ROOT}/openshell/configs/images.env"

NAME="pav-$$"
OLD_NAME="${NAME}"
RECREATE_NAME="pavr-$$"
td="$(mktemp -d)"
: >"${td}/requests"
server=""
cleanup() {
  harness_destroy "${OLD_NAME}"
  harness_destroy "${RECREATE_NAME}"
  [[ -z "${server}" ]] || kill "${server}" 2>/dev/null || true
  rm -rf "${td}"
}
trap cleanup EXIT

audit="${td}/approvals.jsonl"
server_bind=0.0.0.0
python3 "${ROOT}/openshell/tests/controlled-http.py" "${td}/requests" "${server_bind}" & server=$!
for ((i=0; i<20; i++)); do
  if curl -s "http://127.0.0.1:18080" >/dev/null; then break; fi
  sleep 1
done
kill -0 "${server}"

cat >"${td}/base.yaml" <<'YAML'
version: 1
filesystem_policy: {include_workdir: true, read_only: [/usr, /lib, /lib64, /etc, /proc, /dev/urandom, /opt], read_write: [/sandbox, /tmp, /dev/null, /home]}
landlock: {compatibility: best_effort}
YAML
cp "${td}/base.yaml" "${td}/deny.yaml"
cat >>"${td}/deny.yaml" <<'YAML'
network_policies:
  unrelated:
    name: unrelated
    endpoints: [{host: host.openshell.internal, port: 1, enforcement: enforce}]
    binaries: [{path: /usr/bin/node-26}]
YAML

harness_create "${NAME}" "${ODH_OPENCODE_IMAGE}" "${td}/deny.yaml" "" yes
harness_ssh "${NAME}" 'cat >/tmp/probe.mjs' <"${ROOT}/openshell/tests/probe.mjs"

probe_denied() {
  local before after
  before="$(wc -l <"${td}/requests")"
  if harness_ssh "${NAME}" 'node /tmp/probe.mjs http://host.openshell.internal:18080/' >"${td}/probe.json"; then
    die 'denied probe unexpectedly succeeded'
  fi
  python3 - "${td}/probe.json" <<'PY'
import json
import sys

result = json.load(open(sys.argv[1]))
assert result.get("kind") == "transport-error", result
assert result.get("code") == "EACCES", result
PY
  after="$(wc -l <"${td}/requests")"
  [[ "${after}" == "${before}" ]] || die "denied request reached controlled server"
}

probe_allowed() {
  local before after
  before="$(wc -l <"${td}/requests")"
  harness_ssh "${NAME}" 'node /tmp/probe.mjs http://host.openshell.internal:18080/' >"${td}/probe.json" || true
  python3 - "${td}/probe.json" <<'PY'
import json
import sys

result = json.load(open(sys.argv[1]))
assert result.get("kind") == "http", result
assert result["status"] == 401, result
assert result["body"] == "controlled-reachable-401", result
PY
  after="$(wc -l <"${td}/requests")"
  [[ "${after}" -gt "${before}" ]] || die "approved request did not reach controlled server"
}

probe_denied
chunk_id=""
for ((i=0; i<30; i++)); do
  if harness_ssh "${NAME}" 'node --input-type=module' >"${td}/proposal.json" <<'JS'
const payload = {
  intent_summary: "Allow Node to reach the controlled host fixture on port 18080.",
  operations: [{
    addRule: {
      ruleName: "controlled_host_fixture",
      rule: {
        name: "controlled_host_fixture",
        endpoints: [{host: "host.openshell.internal", port: 18080, protocol: "rest", enforcement: "enforce", access: "read-write"}],
        binaries: [{path: "/usr/bin/node-26"}]
      }
    }
  }]
};
const response = await fetch("http://policy.local/v1/proposals", {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify(payload),
  signal: AbortSignal.timeout(10000)
});
if (response.status !== 202) process.exit(1);
const bodyText = await response.text();
const body = JSON.parse(bodyText);
if (body.accepted_chunks <= 0) process.exit(1);
console.log(JSON.stringify({status: response.status, body: bodyText}));
JS
  then
    python3 - "${td}/proposal.json" <<'PY'
import json
import sys

result = json.load(open(sys.argv[1]))
assert result["status"] == 202, result
body = json.loads(result["body"])
assert body["accepted_chunks"] > 0, body
PY
    break
  fi
  sleep 1
done
[[ -s "${td}/proposal.json" ]] || die "agent proposal was not accepted"

for ((i=0; i<30; i++)); do
  pending="$(_os rule get "${NAME}" --status pending | python3 -c 'import re,sys; sys.stdout.write(re.sub(r"\x1b\[[0-9;]*m", "", sys.stdin.read()))')"
  chunk_id="$(printf '%s\n' "${pending}" | awk '$1 == "Chunk:" {print $2; exit}')"
  [[ -n "${chunk_id}" ]] && break
  sleep 1
done
[[ -n "${chunk_id}" ]] || die "no pending network-rule proposal was generated"
printf '%s\n' "${pending}"

OPENSHELL_APPROVAL_AUDIT_FILE="${audit}" \
  "${ROOT}/openshell/scripts/policy-approve.sh" approve "${NAME}" --chunk-id "${chunk_id}" --yes
harness_ssh "${NAME}" 'node --input-type=module' <<JS
const response = await fetch("http://policy.local/v1/proposals/${chunk_id}/wait?timeout=30");
const result = await response.json();
if (response.status !== 200 || result.status !== "approved" || result.policy_reloaded !== true) {
  process.exit(1);
}
JS
probe_allowed

harness_destroy "${OLD_NAME}"
harness_create "${RECREATE_NAME}" "${ODH_OPENCODE_IMAGE}" "${td}/deny.yaml" "" yes
NAME="${RECREATE_NAME}"
harness_ssh "${NAME}" 'cat >/tmp/probe.mjs' <"${ROOT}/openshell/tests/probe.mjs"
probe_denied

python3 - "${audit}" "${OLD_NAME}" "${chunk_id}" <<'PY'
import json
import sys

path, sandbox, chunk_id = sys.argv[1:]
records = [json.loads(line) for line in open(path) if line.strip()]
matches = [record for record in records
           if record.get("sandbox") == sandbox and record.get("chunk_id") == chunk_id]
assert matches, "approval audit record missing"
assert matches[0]["event"] == "openshell.endpoint_grant.approved"
assert matches[0]["reset_on_recreate"] is True
PY

echo 'openshell-policy-advisor: approved grant reset on recreation OK'
