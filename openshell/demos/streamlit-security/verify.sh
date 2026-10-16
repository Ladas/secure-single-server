#!/usr/bin/env bash
set -euo pipefail

SANDBOX="${OPENSHELL_SANDBOX_NAME:-streamlit-demo}"

if [[ ! "${SANDBOX}" =~ ^[a-z][a-z0-9-]{0,62}$ ]]; then
  printf 'error: sandbox name must be a lowercase DNS-style name\n' >&2
  exit 1
fi

run_sandbox_command() {
  local command=$1
  local output
  local status
  shift

  set +e
  output="$(openshell sandbox exec \
    --name "${SANDBOX}" \
    --no-tty \
    --timeout 10 \
    -- env LC_ALL=C bash -lc "${command}" openshell-demo "$@" 2>&1)"
  status=$?
  set -e
  printf '%s\n' "${output}"
  return "${status}"
}

SANDBOX_NAMES="$(openshell sandbox list --names)" || {
  printf 'error: could not list OpenShell sandboxes\n' >&2
  exit 1
}
if ! grep -Fxq "${SANDBOX}" <<<"${SANDBOX_NAMES}"; then
  printf 'error: sandbox %s does not exist\n' "${SANDBOX}" >&2
  exit 1
fi
if ! openshell sandbox provider list "${SANDBOX}"; then
  printf 'error: could not inspect providers for sandbox %s\n' "${SANDBOX}" >&2
  exit 1
fi
if ! run_sandbox_command 'test -f /opt/openshell-demo/app.py'; then
  printf 'error: sandbox %s does not contain the Streamlit demo\n' "${SANDBOX}" >&2
  exit 1
fi

VERIFY_PATH="/tmp/openshell-verify-$$"
DENIED_WRITE_PATH="/opt/openshell-demo/verify-leak-$$"
cleanup_verification_files() {
  # shellcheck disable=SC2016 # Keep $1 and $2 for the sandbox's bash process.
  run_sandbox_command 'rm -f -- "$1" "$2"' \
    "${VERIFY_PATH}" "${DENIED_WRITE_PATH}" >/dev/null 2>&1 || true
}
trap cleanup_verification_files EXIT
# shellcheck disable=SC2016 # Keep $1 for the sandbox's bash process.
POSITIVE_COMMAND='printf demo > "$1" && test "$(cat "$1")" = demo && rm -f -- "$1"'
if ! POSITIVE_OUTPUT="$(run_sandbox_command "${POSITIVE_COMMAND}" "${VERIFY_PATH}")"; then
  printf 'error: the sandbox could not perform the positive /tmp write control\n' >&2
  exit 1
fi
printf '%s\n' "${POSITIVE_OUTPUT}"
# shellcheck disable=SC2016 # Keep $1 for the sandbox's bash process.
if DENIAL_OUTPUT="$(run_sandbox_command 'echo demo > "$1"' "${DENIED_WRITE_PATH}")"; then
  printf 'error: the sandbox accepted a write to its application directory\n' >&2
  exit 1
fi
if ! printf '%s\n' "${DENIAL_OUTPUT}" | grep -Eq 'Permission denied|EACCES'; then
  printf 'error: the application-directory write failed without permission-denied evidence\n' >&2
  exit 1
fi
if READ_DENIAL_OUTPUT="$(run_sandbox_command 'cat /opt/openshell-demo-secret')"; then
  printf 'error: the sandbox accepted a read of the synthetic marker\n' >&2
  exit 1
fi
if ! printf '%s\n' "${READ_DENIAL_OUTPUT}" | grep -Eq 'Permission denied|EACCES'; then
  printf 'error: the synthetic-marker read failed without permission-denied evidence\n' >&2
  exit 1
fi
printf 'verified: OpenShell denied the application-directory write and synthetic-marker read\n'
