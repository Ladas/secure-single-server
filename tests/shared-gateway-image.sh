#!/usr/bin/env bash

set -euo pipefail

TEST_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly TEST_DIR
REPO_DIR="$(cd -- "${TEST_DIR}/.." && pwd)"
readonly REPO_DIR
# shellcheck source=scripts/common/lib.sh
source "${REPO_DIR}/scripts/common/lib.sh"
readonly IMAGE="${PRAXIS_IMAGE:-quay.io/opendatahub/praxis-experimental@sha256:a3006352106c2264427faa79b57cf7b49287f3f9bfffe9b2eef869d3429988e8}"

engine="${CONTAINER_ENGINE:-}"
if [[ -z "${engine}" ]]; then
  if command -v podman >/dev/null 2>&1 && podman info >/dev/null 2>&1; then
    engine=podman
  elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    engine=docker
  else
    printf 'error: a running Podman or Docker Linux VM is required\n' >&2
    exit 1
  fi
fi

"${engine}" image inspect "${IMAGE}" >/dev/null 2>&1 || "${engine}" pull "${IMAGE}" >/dev/null

check_native_image "${engine}" "${IMAGE}"
architecture="$("${engine}" image inspect "${IMAGE}" --format '{{.Architecture}}')"
[[ "$("${engine}" image inspect "${IMAGE}" --format '{{.Config.User}}')" == "1001" ]] ||
  die "Praxis image must declare runtime user 1001"
[[ "$("${engine}" image inspect "${IMAGE}" --format '{{index .Config.Labels "org.opencontainers.image.source"}}')" == \
   "https://github.com/praxis-proxy/experimental" ]] || die "unexpected Praxis image source"

tmp_dir="$(mktemp -d)"
containers=()
cleanup() {
  for name in "${containers[@]}"; do
    "${engine}" rm --force "${name}" >/dev/null 2>&1 || true
  done
  rm -rf "${tmp_dir}"
}
trap cleanup EXIT

awk '
  FNR == NR {
    if ($0 == "filter_chains:") { capture = 1; next }
    if (capture) baseline = baseline $0 ORS
    next
  }
  /# @@BASELINE_FILTER_CHAINS@@/ { printf "%s", baseline; next }
  { print }
' "${REPO_DIR}/configs/all-in-one/shared-gateway.yaml" \
  "${REPO_DIR}/configs/all-in-one/shared-gateway-switchyard.yaml.in" >"${tmp_dir}/switchyard.yaml"
sed -i.bak \
  -e 's/@@JUDGE_MODEL@@/judge-model/g' \
  -e 's/@@WEAK_MODEL@@/weak-model/g' \
  -e 's/@@STRONG_MODEL@@/strong-model/g' \
  "${tmp_dir}/switchyard.yaml"
rm -f "${tmp_dir}/switchyard.yaml.bak"

run_config() {
  local profile="$1" config="$2" name="shared-gateway-config-${1}-$$"
  local -a isolation_args=(
    --user 1001:1001
    --read-only
    --security-opt no-new-privileges
    --cap-drop all
  )
  if [[ "${engine##*/}" == "podman" ]]; then
    isolation_args+=(--userns "keep-id:uid=1001,gid=1001")
  fi
  containers+=("${name}")
  "${engine}" run --detach --name "${name}" \
    "${isolation_args[@]}" \
    --env OPENAI_API_KEY=local-config-test \
    --env ANTHROPIC_API_KEY=local-config-test \
    --env SWITCHYARD_JUDGE_API_KEY=local-config-test \
    --env TOKEN_RATE_LIMIT_VALKEY_URL=redis://praxis:local-config-test@127.0.0.1:9/0 \
    --mount "type=bind,source=${config},target=/etc/praxis/shared-gateway.yaml,readonly" \
    "${IMAGE}" -c /etc/praxis/shared-gateway.yaml >/dev/null

  local state health attempt
  for (( attempt = 0; attempt < 20; attempt++ )); do
    state="$("${engine}" inspect "${name}" --format '{{.State.Status}}')"
    if [[ "${state}" != "running" ]]; then
      "${engine}" logs "${name}" >&2 || true
      printf 'error: %s config container exited\n' "${profile}" >&2
      return 1
    fi
    health="$("${engine}" inspect "${name}" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}')"
    [[ "${health}" == "healthy" ]] && break
    sleep 1
  done
  [[ "${health}" == "healthy" ]] || {
    "${engine}" logs "${name}" >&2 || true
    printf 'error: %s config did not become healthy\n' "${profile}" >&2
    return 1
  }
  "${engine}" rm --force "${name}" >/dev/null
}

run_config memory "${REPO_DIR}/configs/all-in-one/shared-gateway.yaml"
run_config valkey "${REPO_DIR}/configs/all-in-one/shared-gateway-valkey.yaml"
run_config switchyard "${tmp_dir}/switchyard.yaml"

printf 'pinned Praxis image and all rendered configs start on linux/%s\n' "${architecture}"
