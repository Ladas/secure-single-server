#!/usr/bin/env bash
# Disposable host only. One gateway fixture spans schema and policy tests.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
[[ "$(id -u)" == 0 ]] || { echo 'run as root on disposable RHEL 9' >&2; exit 1; }
owner=openshell-ci
[[ ! -e /var/lib/openshell ]] || { echo 'requires clean disposable host, not an existing gateway' >&2; exit 1; }
cleanup() { "${ROOT}/openshell/scripts/uninstall.sh"; }
trap cleanup EXIT
"${ROOT}/openshell/scripts/install.sh" --owner "${owner}"
uid="$(id -u "${owner}")"
# Copy only source files to a location the locked service account can read.
td="$(mktemp -d /var/tmp/openshell-ci.XXXXXX)"
chmod 0755 "${td}"
cp -R "${ROOT}/openshell" "${ROOT}/scripts" "${ROOT}/configs" "${td}/"

# shellcheck disable=SC2016
runuser -u "${owner}" -- env HOME="/var/lib/${owner}" XDG_RUNTIME_DIR="/run/user/${uid}" \
  DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${uid}/bus" \
  bash -ec 'cd /; bash "$1/openshell/tests/openshell-image.sh"; python3 "$1/openshell/tests/schema.py"; bash "$1/openshell/tests/credentials.sh"; bash "$1/openshell/tests/openshell-policy.sh"' -- "${td}"
rm -rf "${td}"
echo 'Runtime schema and policy checks passed. Praxis inference is a separate qualification test.'
