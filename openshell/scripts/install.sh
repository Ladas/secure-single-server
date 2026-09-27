#!/usr/bin/env bash
set -euo pipefail
OS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=./lib.sh
# shellcheck disable=SC1091
source "${OS_DIR}/scripts/lib.sh"
# shellcheck source=./gateway-lib.sh
# shellcheck disable=SC1091
source "${OS_DIR}/scripts/gateway-lib.sh"
require_root
[[ $# == 2 && "$1" == --owner && "$2" =~ ^[a-z_][a-z0-9_-]*$ ]] || die 'usage: sudo install.sh --owner openshell-svc (dedicated locked account)'
owner="$2"
[[ "${owner}" != praxis-svc && "${owner}" != root ]] || die 'use a separate OpenShell service account'
marker=/etc/secure-single-server/openshell/owner
if [[ -e "${marker}" ]]; then
  [[ "$(cat "${marker}")" == "${owner}" ]] || die 'OpenShell add-on owner differs'
fi
manifest=/etc/secure-single-server/openshell/addon.manifest
if [[ -f "${manifest}" ]]; then
  sha256sum --check --status "${manifest}" || die 'OpenShell managed config drift; preserve your edits before reinstalling'
fi
cd /
umask 077
for cmd in podman python3 curl runuser systemctl; do require_command "$cmd"; done
PRAXIS_SERVICE_USER="${owner}" PRAXIS_CONFIG_DIR=/etc/secure-single-server/openshell \
  "${REPO_ROOT}/scripts/common/install" --prepare
uid="$(id -u "${owner}")"
owner_home="$(getent passwd "${owner}" | cut -d: -f6)"
os_run() {
  runuser -u "${owner}" -- env HOME="${owner_home}" XDG_RUNTIME_DIR="/run/user/${uid}" \
    DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${uid}/bus" "$@"
}
# Apply delegation without restarting the manager (which can kill an installer).
install -d -m 0755 "/etc/systemd/system/user@${uid}.service.d"
printf '[Service]\nDelegate=cpu cpuset io memory pids\n' >"/etc/systemd/system/user@${uid}.service.d/openshell-delegate.conf"
systemctl daemon-reload
controllers="$(cat "/sys/fs/cgroup/user.slice/user-${uid}.slice/user@${uid}.service/cgroup.controllers")"
for controller in cpu cpuset io memory pids; do
  [[ " ${controllers} " == *" ${controller} "* ]] || die "delegation needs host reboot before installation: ${controller} unavailable"
done
os_run systemctl --user enable --now podman.socket
os_run podman info >/dev/null
[[ -S "/run/user/${uid}/podman/podman.sock" ]] || die 'rootless Podman socket unavailable'
if [[ -d /var/lib/openshell ]]; then
  [[ "$(stat -c %u /var/lib/openshell)" == "${uid}" ]] || die '/var/lib/openshell belongs to another owner; migrate explicitly'
fi
install -d -o "${owner}" -g "$(id -gn "${owner}")" -m 0700 /var/lib/openshell
for img in "${ODH_GATEWAY_IMAGE}" "${ODH_SUPERVISOR_IMAGE}" "${ODH_SANDBOX_IMAGE}" "${ODH_CLI_IMAGE}" \
           "${ODH_OPENCODE_IMAGE}" "${ODH_OPENCLAW_IMAGE}" "${ODH_CODEX_IMAGE}"; do
  os_run podman pull "${img}"
done
gateway_ensure_certificates os_run
# Private extraction; always install the binary from the reviewed image.
td="$(mktemp -d)"; cid=""
cleanup() { [[ -z "${cid}" ]] || os_run podman rm -f "${cid}" >/dev/null; rm -rf "${td}"; }
trap cleanup EXIT
cid="$(os_run podman create "${ODH_CLI_IMAGE}")"
os_run podman cp "${cid}:/usr/local/bin/openshell" - | tar -x -C "${td}"
"${td}/openshell" --version
install -m 0755 "${td}/openshell" /usr/local/bin/openshell
os_run mkdir -p "${owner_home}/.config/openshell"
units="/etc/containers/systemd/users/${uid}"
# Existing files must belong to this add-on before replacement.
if [[ ! -e "${marker}" ]]; then
  [[ ! -e "${units}/openshell-gateway.container" && ! -e "${owner_home}/.config/openshell/gateway.toml" ]] || die 'unmanaged OpenShell configuration exists'
  printf '%s\n' "${owner}" >"${marker}"
fi
gateway_install_config "${owner}" "${owner_home}" "${td}" "${ODH_OPENCODE_IMAGE}" yes
sha256sum "${owner_home}/.config/openshell/gateway.toml" "${units}/openshell-gateway.container" >"${manifest}.new"
mv -f "${manifest}.new" "${manifest}"
gateway_start os_run /usr/local/bin/openshell "${owner_home}/.config/openshell/addon-registered"
note "OpenShell ready as ${owner}; rerun safely to recover a partial installation. Praxis files are untouched."
