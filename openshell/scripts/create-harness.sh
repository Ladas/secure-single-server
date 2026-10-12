#!/usr/bin/env bash
set -euo pipefail
C_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${C_DIR}/harness-lib.sh"
HARNESS_KIND="$1"; shift
H_DIR="$(cd -- "${C_DIR}/../harnesses/${HARNESS_KIND}" && pwd)"
PROFILE=""; NAME=""; HARNESS_CONFIG_DIR=""; PROVIDER=""; POLICY_ADVISOR=no
while [[ $# -gt 0 ]]; do
  if [[ "$1" == --policy-advisor ]]; then POLICY_ADVISOR=yes; shift; continue; fi
  [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || die "missing value for $1"
  case "$1" in
    --provider) PROVIDER="$2"; shift 2;;
    --profile) PROFILE="$2"; shift 2;;
    --name) NAME="$2"; shift 2;;
    --config) HARNESS_CONFIG_DIR="$2"; shift 2;;
    *) die "unknown arg: $1";;
  esac
done
[[ -n "${PROFILE}" ]] || die 'usage: create.sh --profile <profile> [--name N] [--config <dir>] [--policy-advisor]'
[[ "${NAME:-sandbox}" =~ ^[a-zA-Z0-9][a-zA-Z0-9-]*$ ]] || die 'invalid sandbox name'
NAME="${NAME:-${HARNESS_KIND}-${PROFILE}}"
# Select workload and policy from data; no per-harness profile allowlist.
backend="${OPENSHELL_BOOTC_BACKEND:-}"
if [[ -n "${backend}" && "${backend}" != cloud && -n "${PROVIDER}" ]]; then
  die 'selected backend owns provider configuration; omit --provider'
fi
REQUESTED_CONFIG="${HARNESS_CONFIG_DIR}"
selection="$("${C_DIR}/template.sh" select --harness "${HARNESS_KIND}" --profile "${PROFILE}" \
  --config "${HARNESS_CONFIG_DIR}" --backend "${backend}")"
TEMPLATE_BACKEND=""; POLICY_SRC=""; DEFAULT_MODEL=""; IMAGE_VARIABLE=""
{
  # shellcheck disable=SC2034 # consumed by harness_create in the shared library
  IFS= read -r TEMPLATE_BACKEND
  IFS= read -r POLICY_SRC
  IFS= read -r HARNESS_CONFIG_DIR
  IFS= read -r DEFAULT_MODEL
  IFS= read -r IMAGE_VARIABLE
} <<<"${selection}"
IMAGE="${!IMAGE_VARIABLE}"
if [[ -n "${HARNESS_CONFIG_DIR}" ]]; then
  [[ -z "${PROVIDER}" ]] || die 'integrated mode cannot attach a direct provider'
  PROVIDER_SRC="${HARNESS_CONFIG_DIR}/harness-provider.json.in"
  [[ -f "${PROVIDER_SRC}" ]] || die "provider template not found: ${PROVIDER_SRC}"
  if [[ -n "${backend}" && "${backend}" != cloud ]]; then
    # Preserve bootc's ownership of the local recipe's model and Praxis port.
    # The model comes from catalog data, not a harness-specific shell branch.
    OPENSHELL_MODEL_ID="${DEFAULT_MODEL}"
    PRAXIS_PORT=8080
  else
    OPENSHELL_MODEL_ID="${OPENSHELL_MODEL_ID:-${DEFAULT_MODEL}}"
  fi
  : "${OPENSHELL_MODEL_ID:?set OPENSHELL_MODEL_ID to the administrator-approved model id}"
  PRAXIS_PORT="${PRAXIS_PORT:-8080}"
  validate_praxis_port
  PRAXIS_API_PREFIX="${PRAXIS_API_PREFIX:-}"
  case "${HARNESS_KIND}" in
    opencode)
      case "${PRAXIS_API_PREFIX}" in ''|/vllm) ;; *) die 'PRAXIS_API_PREFIX must be empty (cloud/bootc) or /vllm (mutable Qwen)' ;; esac
      ;;
    openclaw)
      if [[ -n "${PRAXIS_API_PREFIX}" && "${PRAXIS_API_PREFIX}" != /vllm &&
            ! "${PRAXIS_API_PREFIX}" =~ ^/providers/[a-z][a-z0-9-]{0,31}$ ]]; then
        die 'PRAXIS_API_PREFIX must be empty, /vllm, or /providers/LOWERCASE-SLUG'
      fi
      ;;
    *) die "Praxis integration for ${HARNESS_KIND} is not qualified" ;;
  esac
fi
# Validate all per-instance input before synchronizing or creating anything.
[[ -z "${PROVIDER}" || "${PROVIDER}" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]] || die 'invalid provider name'
TEMPLATE="$("${C_DIR}/template.sh" ensure --harness "${HARNESS_KIND}" --profile "${PROFILE}" \
  --config "${REQUESTED_CONFIG}" --backend "${backend}")"
if [[ -n "${HARNESS_CONFIG_DIR}" ]]; then
  POL="$(mktemp)"; PROV="$(mktemp)"
  # shellcheck disable=SC2329,SC2317 # cleanup is invoked by the EXIT trap
  cleanup() { rm -f "${POL}" "${PROV}"; }
  trap cleanup EXIT
  sed "s#@@PRAXIS_PORT@@#${PRAXIS_PORT}#g" "${POLICY_SRC}" >"${POL}"
  python3 "${C_DIR}/render-${HARNESS_KIND}.py" \
    "${PROVIDER_SRC}" "${PROV}" "${PRAXIS_PORT}" "${OPENSHELL_MODEL_ID}" "${PRAXIS_API_PREFIX}"
  harness_create "${NAME}" "${IMAGE}" "${POL}" "" "${POLICY_ADVISOR}" "${TEMPLATE}"
  case "${HARNESS_KIND}" in
    opencode)
      harness_ssh "${NAME}" 'mkdir -p ~/.config/opencode && cat > ~/.config/opencode/opencode.json' <"${PROV}"
      note "Provider config installed at ~/.config/opencode/opencode.json (Praxis loopback :${PRAXIS_PORT}, model ${OPENSHELL_MODEL_ID})"
      note "Connect with: ${H_DIR}/connect.sh --name ${NAME}"
      ;;
    openclaw)
      initialized=no
      for (( attempt=0; attempt<30; attempt++ )); do
        settings_log="$(_os logs "${NAME}")"
        if [[ "${settings_log}" == *"Acknowledged initial policy revision as loaded"* ]]; then
          initialized=yes
          break
        fi
        sleep 1
      done
      [[ "${initialized}" == yes ]] || die 'OpenShell initial policy revision did not settle; sandbox created but model configuration not installed'
      harness_ssh "${NAME}" 'umask 077; mkdir -p /home/node/.openclaw && cat > /home/node/.openclaw/openclaw.json' <"${PROV}"
      note "OpenClaw Praxis configuration installed; run with openshell/harnesses/openclaw/run.sh --name ${NAME} --message <task>"
      ;;
  esac
else
  harness_create "${NAME}" "${IMAGE}" "${POLICY_SRC}" "${PROVIDER}" "${POLICY_ADVISOR}" "${TEMPLATE}"
  if [[ "${HARNESS_KIND}" == openclaw ]]; then
    note "Open a shell with: ${H_DIR}/connect.sh --name ${NAME}"
  else
    note "Connect with: ${H_DIR}/connect.sh --name ${NAME}"
  fi
fi
