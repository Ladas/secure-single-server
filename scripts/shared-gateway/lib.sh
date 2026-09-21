#!/usr/bin/env bash

set -euo pipefail

readonly SERVICE_USER="${PRAXIS_SERVICE_USER:-praxis-svc}"
readonly CONFIG_DIR="${PRAXIS_CONFIG_DIR:-/etc/praxis}"
# Consumed by scripts that source this library.
# shellcheck disable=SC2034
readonly PROFILE_FILE="${CONFIG_DIR}/shared-gateway.profile"
readonly MANIFEST_FILE="${CONFIG_DIR}/shared-gateway.manifest"
# Consumed by the installer that sources this library.
# shellcheck disable=SC2034
readonly DEFAULT_PRAXIS_IMAGE="quay.io/opendatahub/praxis-experimental@sha256:a3006352106c2264427faa79b57cf7b49287f3f9bfffe9b2eef869d3429988e8"

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

note() {
  printf '%s\n' "$*"
}

require_root() {
  [[ "${EUID}" -eq 0 ]] || die "run this command as root"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

oci_architecture() {
  case "$1" in
    x86_64|amd64) printf 'amd64\n' ;;
    aarch64|arm64) printf 'arm64\n' ;;
    *) die "unsupported architecture: $1" ;;
  esac
}

require_linux_image_platform() {
  local image="$1" image_os="$2" image_arch="$3" expected_arch="$4"
  [[ "${image_os}/${image_arch}" == "linux/${expected_arch}" ]] ||
    die "${image} platform ${image_os}/${image_arch} does not match Linux host ${expected_arch}"
}

check_native_image() {
  local engine="$1" image="$2" server_platform image_platform expected_arch
  case "${engine##*/}" in
    podman) server_platform="$("${engine}" info --format '{{.Host.OS}}/{{.Host.Arch}}')" ;;
    docker) server_platform="$("${engine}" info --format '{{.OSType}}/{{.Architecture}}')" ;;
    *) die "supported container engines are podman and docker" ;;
  esac
  [[ "${server_platform%%/*}" == linux ]] || die "a Linux container-engine server is required"
  expected_arch="$(oci_architecture "${server_platform#*/}")"
  image_platform="$("${engine}" image inspect "${image}" --format '{{.Os}}/{{.Architecture}}')"
  require_linux_image_platform "${image}" "${image_platform%%/*}" "${image_platform#*/}" "${expected_arch}"
}

valkey_acl() {
  local password_hash="$1"
  [[ "${password_hash}" =~ ^[0-9a-f]{64}$ ]] || die "invalid Valkey password hash"
  printf 'user default off\n'
  printf 'user praxis on #%s ~secure-single-server:limits:* +ping +eval +time +get +set +exists +incr +hget +hmget +hgetall +hset +hdel +zadd +zrem +zrange +zcard +zscore +zremrangebyscore +pexpire\n' "${password_hash}"
}

service_uid() {
  id -u "${SERVICE_USER}" 2>/dev/null || die "service account ${SERVICE_USER} does not exist; run install --prepare first"
}

service_gid() {
  id -g "${SERVICE_USER}" 2>/dev/null || die "service account ${SERVICE_USER} does not exist; run install --prepare first"
}

service_home() {
  getent passwd "${SERVICE_USER}" | awk -F: '{print $6}'
}

as_service() {
  local uid home
  uid="$(service_uid)"
  home="$(service_home)"
  [[ -n "${home}" ]] || die "could not resolve ${SERVICE_USER} home"
  runuser -u "${SERVICE_USER}" -- env \
    HOME="${home}" \
    XDG_RUNTIME_DIR="/run/user/${uid}" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${uid}/bus" \
    "$@"
}

validate_secret_name() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || die "invalid Podman secret name: $1"
}

validate_model_name() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._:/-]*$ ]] || die "invalid model name: $1"
}

validate_digest_image() {
  [[ "$1" =~ ^[^[:space:]@]+@sha256:[0-9a-f]{64}$ ]] ||
    die "image must be an immutable NAME@sha256:DIGEST reference: $1"
}

secret_exists() {
  as_service podman secret inspect "$1" >/dev/null 2>&1
}

require_secret() {
  validate_secret_name "$1"
  secret_exists "$1" || die "rootless Podman secret not found for ${SERVICE_USER}: $1"
}

escape_sed_replacement() {
  printf '%s' "$1" | sed 's/[&|\\]/\\&/g'
}

render_template() {
  local source="$1" destination="$2"
  shift 2
  cp "${source}" "${destination}"
  while (( "$#" )); do
    local key="$1" value="$2" escaped
    shift 2
    escaped="$(escape_sed_replacement "${value}")"
    sed -i "s|@@${key}@@|${escaped}|g" "${destination}"
  done
  if grep -Eq '@@[A-Z0-9_]+@@' "${destination}"; then
    die "unresolved template placeholder in ${source}"
  fi
}

sha256_file() {
  sha256sum "$1" | awk '{print $1}'
}

selinux_path_regex() {
  local escaped
  escaped="$(printf '%s' "$1" | sed 's/[][(){}.*+?^$|\\]/\\&/g')"
  printf '^%s$\n' "${escaped}"
}

validate_owned_path() {
  local path="$1" uid
  uid="$(service_uid)"
  case "${path}" in
    "${CONFIG_DIR}/shared-gateway.yaml"|"${CONFIG_DIR}/shared-gateway.profile"|"${CONFIG_DIR}/valkey.conf"|"/etc/containers/systemd/users/${uid}/praxis.container"|"/etc/containers/systemd/users/${uid}/praxis.network"|"/etc/containers/systemd/users/${uid}/praxis-valkey.container"|"/etc/containers/systemd/users/${uid}/praxis-valkey.volume") ;;
    *) die "manifest contains an unmanaged path: ${path}" ;;
  esac
}

verify_managed_manifest() {
  [[ -f "${MANIFEST_FILE}" ]] || die "managed manifest not found: ${MANIFEST_FILE}"
  local expected path actual
  while read -r expected path; do
    [[ -n "${expected}" && -n "${path}" ]] || die "invalid managed manifest entry"
    validate_owned_path "${path}"
    [[ -f "${path}" ]] || die "managed file is missing: ${path}"
    actual="$(sha256_file "${path}")"
    [[ "${actual}" == "${expected}" ]] || die "managed file has drifted: ${path}"
  done <"${MANIFEST_FILE}"
}
