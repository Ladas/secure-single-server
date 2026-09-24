#!/usr/bin/env bash

set -euo pipefail

TEST_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly TEST_DIR
REPO_DIR="$(cd -- "${TEST_DIR}/.." && pwd)"
readonly REPO_DIR
# shellcheck source=scripts/common/lib.sh
source "${REPO_DIR}/scripts/common/lib.sh"
readonly IMAGE="${VALKEY_IMAGE:-docker.io/valkey/valkey@sha256:63346cb24a61221e76bdf41acce99b3968a9fa83d8122144deab45394b27b4f2}"
readonly TEST_PASSWORD="local-valkey-test"
readonly TEST_PASSWORD_HASH="69d6dc9618d24d693cad07557702696090d0f575d9c0868384b8001fd1252358"

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
[[ "$("${engine}" image inspect "${IMAGE}" --format '{{index .Config.Labels "org.opencontainers.image.source"}}')" == \
   "https://github.com/valkey-io/valkey" ]] || die "unexpected Valkey image source"

suffix="$$"
container="shared-gateway-valkey-${suffix}"
network="shared-gateway-valkey-${suffix}"
volume="shared-gateway-valkey-${suffix}"
tmp_dir="$(mktemp -d)"
cleanup() {
  "${engine}" rm --force "${container}" >/dev/null 2>&1 || true
  "${engine}" network rm "${network}" >/dev/null 2>&1 || true
  "${engine}" volume rm "${volume}" >/dev/null 2>&1 || true
  rm -rf "${tmp_dir}"
}
trap cleanup EXIT

sed "s/SHA256_PASSWORD/${TEST_PASSWORD_HASH}/" \
  "${REPO_DIR}/configs/common/valkey/users.acl.example" >"${tmp_dir}/users.acl"

"${engine}" network create "${network}" >/dev/null
"${engine}" volume create "${volume}" >/dev/null
isolation_args=(
  --user 999:999
  --read-only
  --security-opt no-new-privileges
  --cap-drop all
)
if [[ "${engine##*/}" == "podman" ]]; then
  isolation_args+=(--userns "keep-id:uid=999,gid=999")
fi
"${engine}" run --detach --name "${container}" \
  "${isolation_args[@]}" \
  --network "${network}" \
  --mount "type=volume,source=${volume},target=/data" \
  --mount "type=bind,source=${REPO_DIR}/configs/common/valkey/valkey.conf,target=/usr/local/etc/valkey/valkey.conf,readonly" \
  --mount "type=bind,source=${tmp_dir}/users.acl,target=/run/secrets/users.acl,readonly" \
  "${IMAGE}" valkey-server /usr/local/etc/valkey/valkey.conf >/dev/null

client() {
  "${engine}" run --rm --network "${network}" "${IMAGE}" \
    valkey-cli -h "${container}" --user praxis -a "${TEST_PASSWORD}" "$@" 2>/dev/null
}

reply=""
for (( attempt = 0; attempt < 20; attempt++ )); do
  if [[ "$("${engine}" inspect "${container}" --format '{{.State.Status}}')" != "running" ]]; then
    "${engine}" logs "${container}" >&2 || true
    printf 'error: Valkey exited before it became ready\n' >&2
    exit 1
  fi
  reply="$(client ping 2>/dev/null || true)"
  [[ "${reply}" == "PONG" ]] && break
  sleep 1
done
[[ "${reply}" == "PONG" ]] || {
  printf 'error: authenticated Valkey PING did not return PONG; check the ACL and readiness\n' >&2
  exit 1
}

unauthenticated="$("${engine}" run --rm --network "${network}" "${IMAGE}" \
  valkey-cli -h "${container}" ping 2>&1 || true)"
grep -Eq 'NOAUTH|DENIED' <<<"${unauthenticated}"

wrong_password="$("${engine}" run --rm --network "${network}" "${IMAGE}" \
  valkey-cli -h "${container}" --user praxis -a wrong-password ping 2>&1 || true)"
grep -q 'WRONGPASS' <<<"${wrong_password}"

forbidden="$(client set outside:key value 2>&1 || true)"
grep -q 'NOPERM' <<<"${forbidden}"
forbidden="$(client flushall 2>&1 || true)"
grep -q 'NOPERM' <<<"${forbidden}"

[[ "$(client eval "return redis.call('SET',KEYS[1],'persisted')" 1 secure-single-server:limits:probe)" == "OK" ]] ||
  die "Valkey ACL did not permit the namespaced Lua write"
sleep 2
"${engine}" restart "${container}" >/dev/null
for (( attempt = 0; attempt < 20; attempt++ )); do
  reply="$(client get secure-single-server:limits:probe 2>/dev/null || true)"
  [[ "${reply}" == "persisted" ]] && break
  sleep 1
done
[[ "${reply}" == "persisted" ]] || die "Valkey state did not survive restart"
[[ -z "$("${engine}" port "${container}")" ]] || die "Valkey has a published port"

printf 'Valkey ACL, private exposure, and AOF restart checks passed on %s\n' "${IMAGE}"
