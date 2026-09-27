#!/usr/bin/env bash
# Explicit qualification test, not an HTTP-error-as-denial heuristic.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../openshell/scripts/harness-lib.sh
# shellcheck disable=SC1091
source "${ROOT}/openshell/scripts/harness-lib.sh"
: "${OPENSHELL_MODEL_ID:?set the model exposed by the test Praxis/mock-provider fixture}"
NAME="ospx-smoke-$$"
cleanup() { harness_destroy "${NAME}"; }
trap cleanup EXIT
"${ROOT}/openshell/harnesses/opencode/create.sh" --name "${NAME}" --profile dev --config "${ROOT}/configs/openshell-praxis"
harness_ssh "${NAME}" 'node --version' >/dev/null
# Successful inference is mandatory; a 401 or failed SSH must fail qualification.
harness_ssh "${NAME}" 'node --input-type=module' <<'JS'
import fs from 'node:fs';
const c=JSON.parse(fs.readFileSync(process.env.HOME+'/.config/opencode/opencode.json'));
const p=c.provider.praxis;
const response=await fetch(p.options.baseURL+'/chat/completions', {
 method:'POST',headers:{'Content-Type':'application/json'},
 body:JSON.stringify({model:Object.keys(p.models)[0],messages:[{role:'user',content:'Reply OK'}],max_tokens:8}),
 signal:AbortSignal.timeout(30000)});
if(!response.ok) throw new Error('Praxis inference failed: HTTP '+response.status);
const data=await response.json();
if(!data.choices?.length) throw new Error('Missing completion');
console.log('Praxis inference: OK');
JS
# Separate controlled fixture proves network denial; inference alone does not.
bash "${ROOT}/openshell/tests/openshell-policy.sh"
echo 'openshell-praxis-smoke: OK'
