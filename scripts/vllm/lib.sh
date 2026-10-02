#!/usr/bin/env bash
# Shared state helpers for the vLLM installer.
# shellcheck disable=SC2154

cleanup_install() {
  if (( unit_staged )); then
    if [[ -n "${unit_backup}" ]]; then
      mv -f "${unit_backup}" "${unit}"
      mv -f "${manifest_backup}" "${state}/manifest"
    else
      rm -f "${unit}" "${state}/manifest"
    fi
  fi
  if (( template_staged )); then
    if [[ -n "${template_backup}" ]]; then
      mv -f "${template_backup}" "${state}/chat-template.jinja"
    else
      rm -f "${state}/chat-template.jinja"
    fi
    if [[ -n "${template_hash_backup}" ]]; then
      mv -f "${template_hash_backup}" "${state}/template.sha256"
    else
      rm -f "${state}/template.sha256"
    fi
  fi
  if (( fcontext_staged )); then
    semanage fcontext -d "${fcontext_regex}" >/dev/null 2>&1 || true
  fi
  if (( fcontext_staged || fcontext_owned_staged )); then
    rm -f "${fcontext_owned}"
  fi
  if (( service_touched )); then
    as_service systemctl --user stop praxis-vllm.service || true
    as_service systemctl --user daemon-reload || true
    if (( service_was_active )); then
      as_service systemctl --user restart praxis-vllm.service || true
    fi
  fi
  rm -f "${temporary}" "${manifest_new}" "${unit_backup}" "${manifest_backup}" \
    "${template_backup}" "${template_hash_backup}"
  if (( network_staged )); then
    as_service systemctl --user stop praxis-network.service || true
    rm -f "${network_unit}" "${state}/network-owned"
    as_service podman network rm praxis-private >/dev/null 2>&1 || true
    as_service systemctl --user daemon-reload || true
  fi
}

commit_install_state() {
  printf '%s\n' "${mode}" >"${state}/mode"
  printf '%s\n' "${model}" >"${state}/model"
  if (( network_staged || network_adopted )); then
    touch "${state}/network-owned"
  fi
  if [[ -n "${remote_listen}" ]]; then
    printf '%s\n' "${remote_listen}" >"${state}/listen-address"
  else
    rm -f "${state}/listen-address"
  fi
  unit_staged=0
  template_staged=0
  fcontext_staged=0
  fcontext_owned_staged=0
  network_staged=0
  service_touched=0
}
