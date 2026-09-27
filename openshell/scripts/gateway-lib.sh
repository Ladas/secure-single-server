#!/usr/bin/env bash
# Shared gateway operations. Callers own accounts, image pulls and config manifests.
# Source lib.sh first; runner functions supply the service owner's environment.

gateway_ensure_certificates() {  # <runner>
  local runner="$1"
  # Machine keys survive both add-on reinstalls and OS deployment changes.
  if [[ ! -s /var/lib/openshell/tls/jwt/signing.pem ]]; then
    "${runner}" podman run --rm --pull=never --userns=keep-id:uid=1001,gid=1001 --user=1001:1001 \
      -e HOME=/var/lib/openshell -e XDG_DATA_HOME=/var/lib/openshell \
      -v /var/lib/openshell:/var/lib/openshell:z "${ODH_GATEWAY_IMAGE}" generate-certs \
      --output-dir /var/lib/openshell/tls --server-san 127.0.0.1 --server-san localhost --server-san host.openshell.internal
  fi
}

gateway_install_config() {  # <owner> <home> <temporary-directory> <workload-image> <autostart: yes|no>
  local owner="$1" owner_home="$2" tmp="$3" workload="$4" autostart="$5" units
  case "${autostart}" in yes|no) ;; *) die 'gateway autostart must be yes or no' ;; esac
  units="/etc/containers/systemd/users/$(id -u "${owner}")"
  render_openshell_template "${OPENSHELL_DIR}/configs/gateway/gateway.toml.in" "${tmp}/gateway.toml" "${workload}"
  render_openshell_template "${OPENSHELL_DIR}/configs/quadlet/openshell-gateway.container.in" "${tmp}/gateway.container"
  if [[ "${autostart}" == no ]]; then
    sed '/^\[Install\]/,$d' "${tmp}/gateway.container" >"${tmp}/gateway-no-autostart.container"
    mv "${tmp}/gateway-no-autostart.container" "${tmp}/gateway.container"
  fi
  install -o "${owner}" -g "$(id -gn "${owner}")" -m 0600 "${tmp}/gateway.toml" "${owner_home}/.config/openshell/gateway.toml"
  install -m 0644 "${tmp}/gateway.container" "${units}/openshell-gateway.container"
}

gateway_start() {  # <runner> <native-cli> <registration-marker>
  local runner="$1" cli="$2" marker="$3" attempt
  "${runner}" systemctl --user daemon-reload
  "${runner}" systemctl --user restart openshell-gateway.service
  for ((attempt=0; attempt<60; attempt++)); do
    if curl --fail --silent http://127.0.0.1:8091/healthz >/dev/null; then break; fi
    sleep 2
  done
  curl --fail --silent http://127.0.0.1:8091/healthz >/dev/null
  if [[ ! -f "${marker}" ]]; then
    "${runner}" "${cli}" gateway add http://127.0.0.1:8090 --name local
    "${runner}" "${cli}" gateway select local
    "${runner}" touch "${marker}"
  fi
  "${runner}" "${cli}" sandbox list >/dev/null
}
