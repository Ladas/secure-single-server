#!/usr/bin/env bash
# Incrementally sync the current branch's changes to a remote checkout.
#
# The bootc host ships no rsync (minimal image, read-only /usr), so this
# transfers per-file `scp -p` over ssh, copying only paths that differ from
# the base ref. Added, modified, and deleted paths are all handled; renames
# arrive from git as copy-plus-delete. Run it from the repository root or
# anywhere inside the checkout, on the administrator's workstation.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)" || { printf 'not inside a git checkout\n' >&2; exit 1; }
cd "${ROOT}"

HOST=""
KEY_FILE=""
BASE="main"
DEST="secure-single-server"
usage() {
  printf 'usage: %s --host USER@HOST [--key KEYFILE] [--base REF] [--dest REMOTE_DIR]\n' "${0##*/}"
  exit 2
}
while [[ $# -gt 0 ]]; do
  [[ $# -ge 2 ]] || usage
  case "$1" in
    --host) HOST="$2" ;;
    --key) KEY_FILE="$2" ;;
    --base) BASE="$2" ;;
    --dest) DEST="$2" ;;
    *) usage ;;
  esac
  shift 2
done
[[ -n "${HOST}" ]] || usage
[[ "${DEST}" =~ ^[A-Za-z0-9._/-]+$ ]] || { printf 'invalid destination path\n' >&2; exit 1; }

ssh_opts=()
[[ -z "${KEY_FILE}" ]] || ssh_opts=(-i "${KEY_FILE}")
remote() { ssh -o BatchMode=yes "${ssh_opts[@]}" "${HOST}" "$@"; }

# Fail before transferring anything if the base ref or connectivity is wrong.
git rev-parse --verify --quiet "${BASE}^{commit}" >/dev/null \
  || { printf 'base ref not found: %s\n' "${BASE}" >&2; exit 1; }
remote true || { printf 'cannot reach %s\n' "${HOST}" >&2; exit 1; }

status="" path="" new_path=""
while IFS= read -r -d '' status && IFS= read -r -d '' path; do
  case "${status}" in
    R*|C*)
      IFS= read -r -d '' new_path
      remote "mkdir -p '${DEST}/$(dirname "${new_path}")'"
      scp -p -q "${ssh_opts[@]}" "${new_path}" "${HOST}:${DEST}/${new_path}"
      remote "rm -f '${DEST}/${path}'"
      printf 'synced %s (removed %s)\n' "${new_path}" "${path}"
      ;;
    D)
      remote "rm -f '${DEST}/${path}'"
      printf 'removed %s\n' "${path}"
      ;;
    A|M)
      remote "mkdir -p '${DEST}/$(dirname "${path}")'"
      scp -p -q "${ssh_opts[@]}" "${path}" "${HOST}:${DEST}/${path}"
      printf 'synced %s\n' "${path}"
      ;;
    *) ;;
  esac
done < <(git diff --name-status -z "${BASE}"...HEAD)

printf 'sync complete: %s -> %s:%s (base %s)\n' "${ROOT}" "${HOST}" "${DEST}" "${BASE}"
