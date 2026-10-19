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

die() { printf '%s\n' "$*" >&2; exit 1; }

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
[[ "${DEST}" =~ ^[A-Za-z0-9._/-]+$ ]] || die 'invalid destination path'

# Seeded non-empty so Bash 3.2 with nounset can expand it, matching the
# convention in harness-lib.sh.
ssh_opts=(-o BatchMode=yes)
[[ -z "${KEY_FILE}" ]] || ssh_opts+=(-i "${KEY_FILE}")
# The read loop below consumes the diff stream on stdin; ssh (-n) and scp
# (redirected) must not drain it, or the loop stops after the first entry.
remote() { ssh -n "${ssh_opts[@]}" "${HOST}" "$@"; }

# Every path is interpolated into a remote shell command and into scp's remote
# target. scp hands that target to a remote shell before OpenSSH 9 and treats
# it literally under the SFTP backend from 9 on, so no single quoting is
# correct for both; refuse unusual paths rather than guess which parser runs.
# Every path this repository tracks is already within this set. A leading dash
# needs no rejection here: local sources are passed to scp as ./PATH, and a
# remote path only ever appears after "host:" or inside quotes.
safe_path() {
  case "$1" in
    *[!A-Za-z0-9._/-]*) return 1 ;;
  esac
  return 0
}
send() {  # <path>
  safe_path "$1" || die "refusing to sync path with unusual characters: $1"
  remote "mkdir -p '${DEST}/$(dirname "$1")'"
  scp -p -q "${ssh_opts[@]}" "./$1" "${HOST}:${DEST}/$1" </dev/null
}
drop() {  # <path>
  safe_path "$1" || die "refusing to remove path with unusual characters: $1"
  remote "rm -f '${DEST}/$1'"
}

# Fail before transferring anything if the base ref or connectivity is wrong.
git rev-parse --verify --quiet "${BASE}^{commit}" >/dev/null \
  || die "base ref not found: ${BASE}"
remote true || die "cannot reach ${HOST}"

# Process substitution hides the diff's exit status, so materialize the stream
# first: a diff that fails -- no merge base with HEAD, for example -- must
# abort here instead of looking like an empty changeset and printing success.
diff_stream="$(mktemp)"
trap 'rm -f "${diff_stream}"' EXIT
git diff --name-status -z "${BASE}"...HEAD >"${diff_stream}"

status="" path="" new_path=""
while IFS= read -r -d '' status && IFS= read -r -d '' path; do
  case "${status}" in
    R*)
      IFS= read -r -d '' new_path
      send "${new_path}"
      drop "${path}"
      printf 'synced %s (removed %s)\n' "${new_path}" "${path}"
      ;;
    C*)
      # Git copied the source, which still exists in the branch: transfer the
      # new path only and leave the source in place on the remote.
      IFS= read -r -d '' new_path
      send "${new_path}"
      printf 'synced %s (copied from %s)\n' "${new_path}" "${path}"
      ;;
    D)
      drop "${path}"
      printf 'removed %s\n' "${path}"
      ;;
    A|M)
      send "${path}"
      printf 'synced %s\n' "${path}"
      ;;
    *) ;;
  esac
done < "${diff_stream}"

printf 'sync complete: %s -> %s:%s (base %s)\n' "${ROOT}" "${HOST}" "${DEST}" "${BASE}"
