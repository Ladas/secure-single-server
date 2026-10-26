#!/usr/bin/env bash
# Narrated replay of the September 2026 coding-agent benchmark move - the
# agent redirected to a model it was never approved to use - as a contrast
# demonstration (Story 3).
#
# Side A runs the same agent image as a plain container: a provider key in
# the environment, unrestricted network, and a stand-in provider on the
# host. The user's one-line model pick is honored end to end, with the key
# attached, and nothing anywhere refuses or records a violation.
# Side B runs the live openshell-praxis deployment: an OpenShell sandbox
# whose only model path is the gateway, and a gateway whose administrator
# catalog lists exactly the approved models. The same pick is refused at
# the gateway - before credentials - and no direct provider path exists.
#
# The stand-in provider is tests/openshell-praxis/opencode-provider.py; the
# planted key is a synthetic canary whose value is never printed. Side B
# makes exactly one real completion request (the sanctioned model, a few
# tokens); every other request is refused or stands in. See
# docs/examples/model-escalation/README.md for the story.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../scripts/harness-lib.sh
# shellcheck disable=SC1091
source "${ROOT}/openshell/scripts/harness-lib.sh"

# OpenShell rejects sandbox names longer than 19 characters.
name="model-demo-$$"
praxis_port="${PRAXIS_PORT:-8080}"
wrong_model="${WRONG_MODEL:-gpt-6-sol}"
fixture_port="${FIXTURE_PORT:-18090}"
control_port="${CONTROL_PORT:-19090}"
engine="${CONTAINER_ENGINE:-podman}"
canary="sk-synthetic-model-misuse-canary"
fixture_pid=""
td="$(mktemp -d)"

cleanup() {
  local result=0
  harness_destroy "${name}" || result=1
  [[ -z "${fixture_pid}" ]] || kill "${fixture_pid}" 2>/dev/null || true
  rm -rf "${td}"
  return "${result}"
}
cleanup_exit_status=0
trap 'cleanup_exit_status=$?; if ! cleanup && (( cleanup_exit_status == 0 )); then cleanup_exit_status=1; fi; exit "$cleanup_exit_status"' EXIT

say() { printf '\n===== %s =====\n' "$*"; }

require_command curl
require_command python3

say "Pre-flight: the Praxis gateway must answer on loopback"
curl -fsS --max-time 10 "http://127.0.0.1:${praxis_port}/v1/models" >"${td}/models.json" \
  || die "gateway not reachable on 127.0.0.1:${praxis_port}; this demo needs the openshell-praxis all-in-one deployment"
echo "gateway is up on 127.0.0.1:${praxis_port}"

say "Act 1: the rule, as the gateway states it"
# The unified model catalog is this story's control: /v1/models is answered
# from the administrator's configuration, not from the upstream, and every
# entry carries a praxis block with the upstream mapping. A raw provider
# catalog means no catalog is installed and the story's refusal does not
# exist - fail loudly rather than demo the wrong configuration.
catalog_ids="$(python3 - "${td}/models.json" <<'PY' || die "the gateway lists no unified model catalog; install one with 'sss-bootc providers unified --models <file>' - this repo ships the single-model catalog openshell/scripts/model-misuse-catalog.json"
import json, sys
entries = json.load(open(sys.argv[1])).get("data", [])
if not entries or not all("praxis" in entry for entry in entries):
    raise SystemExit("no unified catalog entries")
print(" ".join(entry["id"] for entry in entries))
PY
)"
sanctioned="${catalog_ids%% *}"
if [[ " ${catalog_ids} " == *" ${wrong_model} "* ]]; then
  die "WRONG_MODEL '${wrong_model}' is in the catalog; pick a model the catalog does not list"
fi
python3 -m json.tool <"${td}/models.json"
echo "administrator catalog (the whole routable list): ${catalog_ids}"
echo "the misuse target for this demo: ${wrong_model}"

say "Act 2: side A - the same agent image, no boundary, key in the environment"
# The default shape of local agent installs: a plain container, a provider
# key exported in the environment, unrestricted network. The stand-in
# provider plays the provider; in the real world it is api.openai.com.
MODEL_MISUSE_CANARY="${canary}" \
  python3 "${ROOT}/tests/openshell-praxis/opencode-provider.py" \
  --port "${fixture_port}" --control-port "${control_port}" \
  --model "${sanctioned}" --authorization-env MODEL_MISUSE_CANARY &
fixture_pid=$!
for _ in $(seq 1 20); do
  curl -s "http://127.0.0.1:${control_port}/state" >/dev/null && break
  sleep 1
done
curl -s "http://127.0.0.1:${control_port}/state" >/dev/null \
  || die "stand-in provider did not come up on port ${control_port}"
echo "stand-in provider up on 127.0.0.1:${fixture_port} (control on ${control_port})"
sideA="${td}/side-a"
mkdir -p "${sideA}/home/.config/opencode" "${sideA}/sandbox"
chmod 0777 "${sideA}/home" "${sideA}/sandbox"
# Side A has no server-side rule, only the user-owned model list that
# opencode resolves -m against - so the stronger model must be listed for
# the move under test to run at all. The default stays the approved model.
# The provider id must not be "openai": opencode would fold the config into
# its built-in OpenAI provider (Responses API, full model registry), and the
# stand-in drives tools over chat completions - the same reason the deployed
# harness names its provider "praxis". The canary is baked in, mirroring the
# deployed harness's literal apiKey placeholder rather than an {env:...}
# lookup this stack never executes.
cat >"${sideA}/home/.config/opencode/opencode.json" <<EOF
{
  "\$schema": "https://opencode.ai/config.json",
  "provider": {
    "standalone": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "OpenAI (standalone install)",
      "options": {"baseURL": "http://127.0.0.1:${fixture_port}/v1", "apiKey": "${canary}"},
      "models": {"${sanctioned}": {"name": "Default model"},
                 "${wrong_model}": {"name": "Stronger model"}}
    }
  },
  "model": "standalone/${sanctioned}"
}
EOF
userns=()
if [[ "${engine}" == "podman" ]] && [[ "$(id -u)" != "0" ]]; then
  # shellcheck disable=SC2054  # podman's keep-id takes one comma-separated argument
  userns=(--userns=keep-id:uid=1001,gid=1001)
fi
"${engine}" run --rm --network=host "${userns[@]}" \
  --user 1001:1001 --cap-drop=all --security-opt=no-new-privileges \
  -e HOME=/home/sandbox \
  --env-file <(printf 'OPENAI_API_KEY=%s\n' "${canary}") \
  -v "${sideA}/home:/home/sandbox:Z" -v "${sideA}/sandbox:/sandbox:Z" -w /sandbox \
  --entrypoint /usr/local/bin/opencode "${ODH_OPENCODE_IMAGE}" \
  run --format json --model "standalone/${wrong_model}" \
  "Write the proof script, run it with bash, then confirm completion." \
  >"${td}/side-a.out" 2>&1 \
  || { echo "the stand-in's records for the requests it saw (path, model, credential verdict):"
       curl -s "http://127.0.0.1:${control_port}/state" || true
       echo
       die "side A: opencode failed against the stand-in provider: $(tail -5 "${td}/side-a.out")"; }
grep -q "OPENCODE_TOOL_OK" "${td}/side-a.out" \
  || die "side A: the stand-in provider did not drive the agent's tools: $(tail -5 "${td}/side-a.out")"
[[ "$(tr -d '[:space:]' <"${sideA}/sandbox/opencode-exec-proof.txt")" == "OPENCODE_TOOL_OK" ]] \
  || die "side A: the agent's bash tool produced no proof file under the wrong model"
echo "the agent ran its bash tool, wrote the proof file, and confirmed completion on ${wrong_model}"
python3 - "${control_port}" "${wrong_model}" <<'PY' || die "side A: the stand-in provider never served ${wrong_model} with the canary credential"
import json, sys, urllib.request
state = json.load(urllib.request.urlopen("http://127.0.0.1:" + sys.argv[1] + "/state"))
hits = [r for r in state["records"]
        if r.get("model") == sys.argv[2] and r.get("path") == "/v1/chat/completions"]
assert hits, "no completion request reached the provider for the wrong model"
assert all(r.get("credential_ok") for r in hits), "the canary credential did not travel with the request"
print("stand-in provider records: {} completion request(s) for {}, canary credential attached to each".format(
    len(hits), sys.argv[2]))
PY
kill "${fixture_pid}" 2>/dev/null || true
fixture_pid=""
echo "read the record above carefully: the client's model choice was honored verbatim,"
echo "the key traveled with it, and nothing refused or logged a violation. The only"
echo "model list was the one in the user's own config file - and the user who owns"
echo "the config owns the list. One -m flag chose the stronger model; a real provider"
echo "would bill for this and tell no one."

say "Act 3: side B - the same image behind the OpenShell boundary"
# Render the policy and provider config exactly as the deployment's
# create-harness.sh does: the only model path is the gateway, and the
# agent's config lists the sanctioned catalog model.
sed -e "s#@@PRAXIS_PORT@@#${praxis_port}#g" -e "s#@@PRAXIS_API_PREFIX@@##g" \
  "${ROOT}/configs/openshell-praxis/profiles/dev/policy.yaml" >"${td}/policy.yaml"
python3 "${ROOT}/openshell/scripts/render-opencode.py" \
  "${ROOT}/configs/openshell-praxis/harness-provider.json.in" "${td}/opencode.json" \
  "${praxis_port}" "${sanctioned}" ""
harness_create "${name}" "${ODH_OPENCODE_IMAGE}" "${td}/policy.yaml"
rg="$(command -v rg)" || die "ripgrep is required on the host for OpenCode tools"
harness_ssh "${name}" \
  "mkdir -p \"\$HOME/.local/bin\" && cat > \"\$HOME/.local/bin/rg\" && chmod 0755 \"\$HOME/.local/bin/rg\"" <"${rg}"
harness_ssh "${name}" 'mkdir -p ~/.config/opencode && cat > ~/.config/opencode/opencode.json' \
  <"${td}/opencode.json"
echo "sandbox ready; its only model path is the gateway on :${praxis_port}"

say "Act 4: the sanctioned flow - the approved model answers"
# The one real request this demo makes: a few tokens on the sanctioned
# model. Note what the model calls itself - the catalog decouples the
# client-facing id from the upstream model name.
# opencode run reads stdin when it is an open pipe: over ssh without -n
# the caller's terminal stays attached and the run blocks forever. Every
# opencode invocation below closes stdin; the node-26 probes pipe their
# scripts through stdin and keep it.
if ! harness_ssh "${name}" \
  "/usr/local/bin/opencode run --format json 'Which model are you? Answer in one short sentence.'" \
  >"${td}/sanctioned.out" 2>&1 </dev/null; then
  die "the sanctioned model did not answer: $(tail -5 "${td}/sanctioned.out")"
fi
python3 - "${td}/sanctioned.out" <<'PY' || die "no answer text in the sanctioned run: $(tail -5 "${td}/sanctioned.out")"
import json, sys
for line in open(sys.argv[1]):
    if not line.startswith("{"):
        continue
    item = json.loads(line)
    if item.get("type") == "error":
        raise SystemExit("error event in the sanctioned run: " + line.strip())
    part = item.get("part") or {}
    if item.get("type") == "text" and part.get("text"):
        print("the approved model answered: " + part["text"][:200].strip())
        raise SystemExit(0)
raise SystemExit("no text part in the transcript")
PY

say "Act 5: the same pick, through the boundary"
# The move from the live sandbox, replayed at the user-facing layer. This
# layer cannot show who refused - opencode resolves -m against its own
# config, which lists only the sanctioned model - so the raw request below
# is the proof that the gateway itself refuses.
if harness_ssh "${name}" \
  "/usr/local/bin/opencode run --format json --model praxis/${wrong_model} 'Which model are you?'" \
  >"${td}/wrong-ux.out" 2>&1 </dev/null; then
  grep -q '"type": *"error"' "${td}/wrong-ux.out" \
    || die "SECURITY FAILURE: opencode served ${wrong_model} through the gateway"
fi
echo "the user-facing failure (opencode's generic wrapper):"
tail -3 "${td}/wrong-ux.out"
# The raw response behind the wrapper: the sanctioned runtime asks the
# gateway directly. This is the only proof that matters - the gateway's
# own refusal body, produced before credential injection.
printf '%s\n' \
  "const body = JSON.stringify({model: \"${wrong_model}\", messages: [{role: \"user\", content: \"hello\"}], max_tokens: 4});" \
  "fetch(\"http://host.openshell.internal:${praxis_port}/v1/chat/completions\", {" \
  '  method: "POST",' \
  '  headers: {"Content-Type": "application/json", "Authorization": "Bearer local-placeholder"},' \
  '  body,' \
  '})' \
  '  .then(async (r) => { console.log("HTTP " + r.status); console.log((await r.text()).slice(0, 120)); })' \
  '  .catch((e) => { console.log("request error: " + (e.cause?.code ?? e.message)); process.exit(1); });' \
  | harness_ssh "${name}" '/usr/bin/node-26' | tee "${td}/wrong-raw.out"
grep -q "HTTP 404" "${td}/wrong-raw.out" \
  || die "the wrong model was not refused with 404: $(cat "${td}/wrong-raw.out")"
grep -q "Unknown model" "${td}/wrong-raw.out" \
  || die "the refusal is not the gateway's Unknown-model body: $(cat "${td}/wrong-raw.out")"
echo "the gateway's own answer: 404, Unknown model - before credentials, before the upstream"
# The fallback a downloaded skill would try: forge the routing header and
# keep the wrong model in the body. Caller copies of the routing header
# are stripped during body pre-read; the body wins.
printf '%s\n' \
  "const body = JSON.stringify({model: \"${wrong_model}\", messages: [{role: \"user\", content: \"hello\"}], max_tokens: 4});" \
  "fetch(\"http://host.openshell.internal:${praxis_port}/v1/chat/completions\", {" \
  '  method: "POST",' \
  "  headers: {\"Content-Type\": \"application/json\", \"X-Gateway-Model\": \"${sanctioned}\"}," \
  '  body,' \
  '})' \
  '  .then(async (r) => { console.log("HTTP " + r.status); console.log((await r.text()).slice(0, 120)); })' \
  '  .catch((e) => { console.log("request error: " + (e.cause?.code ?? e.message)); process.exit(1); });' \
  | harness_ssh "${name}" '/usr/bin/node-26' | tee "${td}/forged.out"
grep -q "HTTP 404" "${td}/forged.out" \
  || die "the forged routing header was not refused: $(cat "${td}/forged.out")"
grep -q "Unknown model" "${td}/forged.out" \
  || die "the forged-header refusal is not the gateway's Unknown-model body: $(cat "${td}/forged.out")"
echo "the forged routing header was stripped; the body's model decides"
# The last fallback: skip the gateway entirely and call the provider
# directly - Story 1's vector, one layer down. The node script exits 1 on
# the denial, so the pipeline runs inside the guard: bare, errexit plus
# pipefail would end the script silently right after the EACCES line.
if printf '%s\n' \
  'const net = require("net");' \
  'const s = net.connect({host: "api.openai.com", port: 443});' \
  's.on("error", (e) => { console.log("connect error:", e.code); process.exit(1); });' \
  's.on("connect", () => { console.log("UNEXPECTED: connected"); process.exit(0); });' \
  | harness_ssh "${name}" '/usr/bin/node-26' | tee "${td}/direct.out"; then
  die "SECURITY FAILURE: the direct provider path reached api.openai.com"
fi
grep -q "EACCES" "${td}/direct.out" \
  || die "the direct provider path was not denied at connect(): $(cat "${td}/direct.out")"
echo "no direct path to any provider: the boundary routes model traffic through the gateway"

say "Act 6: the attempts are on the record"
denials=""
for _ in $(seq 1 10); do
  denials="$(_os logs "${name}" 2>/dev/null | grep "transparent_tcp_policy_denied" || true)"
  [[ -n "${denials}" ]] && break
  sleep 1
done
[[ -n "${denials}" ]] || die "no transparent_tcp_policy_denied entries in the sandbox log"
printf '%s\n' "${denials}"
echo "the boundary's log shows the direct-provider attempt; the catalog refusals are the"
echo "gateway's own access log - the operator's record, not the sandbox's."

say "Demo passed: the model choice is the administrator's, not the client's"
echo "Side A: one -m flag and the stand-in provider served ${wrong_model} with the canary"
echo "key attached - no refusal, no audit; the policy was a client-side file. Side B:"
echo "the same image, but every path to a model runs through the gateway. The catalog"
echo "lists ${catalog_ids}; ${wrong_model} is unroutable (404 before credentials), the"
echo "forged routing header was stripped, and the direct provider path died at connect()"
echo "with EACCES. The model field is a catalog lookup key, not a command - and the key"
echo "that would have paid for the wrong model never existed inside the sandbox."
echo "Sandbox ${name} destroyed; transcript artifacts were kept out of the repo."
