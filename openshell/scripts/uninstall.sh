#!/usr/bin/env bash
set -euo pipefail
OS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=./lib.sh
# shellcheck disable=SC1091
source "${OS_DIR}/scripts/lib.sh"
require_root
marker=/etc/secure-single-server/openshell/owner
[[ -f "${marker}" ]] || die 'no managed OpenShell add-on; bootc uses OS deployment rollback'
owner="$(cat "${marker}")"
uid="$(id -u "${owner}")"
owner_home="$(getent passwd "${owner}" | cut -d: -f6)"
os_run() { runuser -u "${owner}" -- env HOME="${owner_home}" XDG_RUNTIME_DIR="/run/user/${uid}" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${uid}/bus" "$@"; }
manifest=/etc/secure-single-server/openshell/addon.manifest
if [[ -f "${manifest}" ]]; then
  sha256sum --check --status "${manifest}" || die 'OpenShell managed config drift; refusing removal'
fi
if [[ -f "/etc/containers/systemd/users/${uid}/openshell-gateway.container" ]]; then
  os_run systemctl --user stop openshell-gateway.service
fi
rm -f "/etc/containers/systemd/users/${uid}/openshell-gateway.container"
rm -f "${manifest}"
os_run systemctl --user daemon-reload
note 'OpenShell gateway stopped and unit removed. Account, lingering, CLI, config, keys, sandbox containers and workspaces are retained. Rerun install to recover; Praxis is untouched.'
