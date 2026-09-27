#!/usr/bin/env bash
set -euo pipefail
H_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../scripts/harness-lib.sh
# shellcheck disable=SC1091
source "${H_DIR}/../../scripts/harness-lib.sh"
# shellcheck source=../../configs/images.env
# shellcheck disable=SC1091
source "${OPENSHELL_DIR:-${H_DIR}/../..}/configs/images.env"
PROFILE=""; NAME=""; HARNESS_CONFIG_DIR=""; PROVIDER=""
while [[ $# -gt 0 ]]; do
  [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || die "missing value for $1"
  case "$1" in
  --provider) PROVIDER="$2"; shift 2;;
  --profile) PROFILE="$2"; shift 2;;
  --name) NAME="$2"; shift 2;;
  --config) HARNESS_CONFIG_DIR="$2"; shift 2;;
  *) die "unknown arg: $1";;
esac; done
[[ -n "${PROFILE}" ]] || die "usage: create.sh --profile <p> [--name N] [--config <dir>]"

case "${PROFILE}" in review|dev|automation|interactive) ;; *) die "no such profile: ${PROFILE}" ;; esac
[[ "${NAME:-sandbox}" =~ ^[a-zA-Z0-9][a-zA-Z0-9-]*$ ]] || die "invalid sandbox name"

if [[ -n "${HARNESS_CONFIG_DIR}" ]]; then
  [[ -z "${PROVIDER}" ]] || die "integrated mode cannot attach a direct provider"
  die "Praxis integration for openclaw is not qualified; --config is unsupported"
fi

PROFILE_DIR="${H_DIR}/profiles/${PROFILE}"
[[ -d "${PROFILE_DIR}" ]] || die "no such profile: ${PROFILE}"
NAME="${NAME:-openclaw-${PROFILE}}"
harness_create "${NAME}" "${ODH_OPENCLAW_IMAGE}" "${PROFILE_DIR}/policy.yaml" "${PROVIDER}"
note "Open a shell with: ${H_DIR}/connect.sh --name ${NAME}"
