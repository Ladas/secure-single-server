#!/usr/bin/env bash

set -euo pipefail

TEST_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly TEST_DIR
REPO_DIR="$(cd -- "${TEST_DIR}/.." && pwd)"
readonly REPO_DIR
# shellcheck source=scripts/common/lib.sh
source "${REPO_DIR}/scripts/common/lib.sh"

require_root
verify_managed_manifest
[[ "$(getenforce)" == "Enforcing" ]] || die "SELinux is not enforcing"
[[ -f /sys/fs/cgroup/cgroup.controllers ]] || die "cgroups v2 is missing"
[[ "$(getent passwd "${SERVICE_USER}" | awk -F: '{print $7}')" =~ /sbin/nologin$ ]] ||
  die "service account has a login shell"
[[ "$(loginctl show-user "${SERVICE_USER}" -p Linger --value)" == "yes" ]] || die "lingering is disabled"
[[ "$(stat -c '%a' "$(service_home)")" == "700" ]] || die "service home is not private"

as_service systemctl --user is-active --quiet praxis.service
as_service podman inspect praxis-shared-gateway --format '{{.State.Status}} {{.Config.User}}' \
  | grep -Eqx 'running 1001(:1001)?'
scenario="all-in-one"
[[ ! -f "${SCENARIO_FILE}" ]] || scenario="$(<"${SCENARIO_FILE}")"
if [[ "${scenario}" == remote-gateway ]]; then
  [[ "$(as_service podman port praxis-shared-gateway)" == "8443/tcp -> 0.0.0.0:8443" ]] ||
    die "remote gateway must publish only HTTPS on 8443"
  if ss -H -ltn | awk '{print $4}' | grep -Eq ':(8080|8081|8082)$'; then
    die "plaintext inference port is host-visible"
  fi
else
  [[ "$(as_service podman port praxis-shared-gateway 8080/tcp)" == "127.0.0.1:8080" ]] || die "unexpected OpenAI port binding"
  [[ "$(as_service podman port praxis-shared-gateway 8081/tcp)" == "127.0.0.1:8081" ]] || die "unexpected Anthropic port binding"
  for port in 8080 8081; do
    ss -H -ltn | awk '{print $4}' | grep -qx "127.0.0.1:${port}"
  done
fi
as_service podman exec praxis-shared-gateway \
  curl --fail --silent http://127.0.0.1:9901/healthy >/dev/null

if ss -H -ltn | awk '{print $4}' | grep -Eq ':(9901|6379|8000)$'; then
  printf 'error: private admin or dependency listener is host-visible\n' >&2
  exit 1
fi
if ss -H -ltn | awk '{print $4}' | grep -E ':(8080|8081|8082)$' | grep -Ev '^127\.0\.0\.1:'; then
  printf 'error: an inference listener is not loopback-only\n' >&2
  exit 1
fi

uid="$(service_uid)"
gid="$(service_gid)"
quadlet_dir="/etc/containers/systemd/users/${uid}"
[[ "$(stat -c '%u:%g %a' "${CONFIG_DIR}/shared-gateway.yaml")" == "0:${gid} 640" ]] || die "unexpected configuration permissions"
stat -c '%C' "${CONFIG_DIR}/shared-gateway.yaml" | grep -q ':container_file_t:'
if [[ "${scenario}" == remote-gateway ]]; then
  for file in policy.yaml jwt-public.pem tls.pem tls-key.pem; do
    [[ "$(stat -c '%u:%g %a' "${CONFIG_DIR}/${file}")" == "0:${gid} 640" ]] || die "unsafe ${file} permissions"
    stat -c '%C' "${CONFIG_DIR}/${file}" | grep -q ':container_file_t:'
  done
fi
[[ "$(stat -c '%u:%g %a' "${quadlet_dir}")" == "0:${gid} 750" ]] || die "unexpected Quadlet directory permissions"
[[ "$(stat -c '%u:%g %a' "${quadlet_dir}/praxis.container")" == "0:${gid} 640" ]] || die "unexpected Quadlet permissions"

profile="$(<"${PROFILE_FILE}")"
case "${profile}" in
  memory) ;;
  switchyard)
    ss -H -ltn | awk '{print $4}' | grep -qx '127.0.0.1:8082'
    [[ "$(as_service podman port praxis-shared-gateway 8082/tcp)" == "127.0.0.1:8082" ]] || die "unexpected Switchyard port binding"
    ;;
  valkey)
    as_service systemctl --user is-active --quiet praxis-valkey.service
    as_service podman inspect praxis-valkey --format '{{.State.Status}} {{.Config.User}}' \
      | grep -Eqx 'running 999(:999)?'
    stat -c '%C' "${CONFIG_DIR}/valkey.conf" | grep -q ':container_file_t:'
    ;;
  *) die "unknown installed profile: ${profile}" ;;
esac

printf 'installed RHEL host checks passed for profile %s\n' "${profile}"
