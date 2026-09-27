#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
OS_DIR="${ROOT}/openshell"
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
# shellcheck source=../scripts/lib.sh
# shellcheck disable=SC1091
source "${OS_DIR}/scripts/lib.sh"

# 1a. images.env must define four @sha256-pinned odh control-plane images.
# (images.env already sourced by lib.sh)
for var in ODH_GATEWAY_IMAGE ODH_SUPERVISOR_IMAGE ODH_SANDBOX_IMAGE ODH_CLI_IMAGE; do
  val="${!var:-}"
  [[ -n "${val}" ]] || fail "${var} unset"
  [[ "${val}" == quay.io/opendatahub/odh-openshell-*@sha256:* ]] \
    || fail "${var} not a digest-pinned odh image: ${val}"
done

# 1b. images.env must define three @sha256-pinned public aipcc harness images.
for var in ODH_OPENCODE_IMAGE ODH_OPENCLAW_IMAGE ODH_CODEX_IMAGE; do
  val="${!var:-}"
  [[ -n "${val}" ]] || fail "${var} unset"
  [[ "${val}" == quay.io/aipcc/base-images/agentic/*@sha256:* ]] \
    || fail "${var} not a digest-pinned aipcc image: ${val}"
done

# 2. All shell scripts under openshell/ pass shellcheck.
if command -v shellcheck >/dev/null 2>&1; then
  mapfile -t scripts < <(find "${OS_DIR}" -name '*.sh' -type f)
  shellcheck -S style "${scripts[@]}" || fail "shellcheck failed"
fi

# 3. Gateway quadlet template renders with no leftover placeholders.
tmp="$(mktemp)"
render_openshell_template "${OS_DIR}/configs/quadlet/openshell-gateway.container.in" "${tmp}"
grep -q '@@' "${tmp}" && fail "unrendered placeholder in gateway quadlet"
grep -q "Image=${ODH_GATEWAY_IMAGE}" "${tmp}" || fail "gateway image not pinned in unit"
grep -q 'Pull=never' "${tmp}" || fail "gateway unit must set Pull=never"
rm -f "${tmp}"

# 4. gateway.toml.in uses the podman driver, JWT auth, and pins workload/supervisor images.
gt="${OS_DIR}/configs/gateway/gateway.toml.in"
grep -q 'compute_driver *= *"podman"' "${gt}" || fail "gateway.toml not podman driver"
grep -q '\[openshell.gateway.gateway_jwt\]' "${gt}" || fail "gateway.toml missing JWT auth block"
grep -q 'supervisor_image *= *"@@ODH_SUPERVISOR_IMAGE@@"' "${gt}" || fail "supervisor image placeholder missing"
grep -q 'default_image *= *"@@ODH_OPENCODE_IMAGE@@"' "${gt}" || fail "default_image must be an aipcc workload image (@@ODH_OPENCODE_IMAGE@@)"

# 5. Structural checks only; schema.py validates with the pinned native CLI.
if command -v python3 >/dev/null 2>&1; then
  while IFS= read -r p; do
    python3 - "$p" <<'PY' || fail "invalid policy: $p"
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]).read().replace("@@PRAXIS_PORT@@", "8080"))
assert d.get("version") == 1, "version"
assert "network_policies" in d, "network_policies"
assert "filesystem_policy" in d, "filesystem_policy"
for name, policy in d["network_policies"].items():
    for endpoint in policy.get("endpoints", []):
        assert type(endpoint["port"]) is int and 1 <= endpoint["port"] <= 65535
        if endpoint.get("protocol") == "rest":
            assert endpoint.get("access") or endpoint.get("rules"), \
                f"{name}: REST endpoint requires access or rules"
PY
  done < <(find "${OS_DIR}" "${ROOT}/configs/openshell-praxis" -path '*/profiles/*/policy.yaml')
fi

python3 "${OS_DIR}/tests/regressions.py"
python3 "${OS_DIR}/tests/gateway.py"
printf 'openshell-static: OK\n'
