#!/usr/bin/env bash
# Mirror the working tree to a remote checkout with rsync.
#
# Unlike sync-branch.sh (committed changes only, per-file scp for the bootc
# host that ships no rsync), this mirrors the whole working tree -
# uncommitted edits included - in one incremental transfer, so fixes can be
# tested on the host before they are committed. Requires rsync on both
# ends; the native RHEL install has it, the minimal bootc image does not.
# The destination is a true mirror: files removed locally are removed
# remotely. Excluded paths (.git, macOS metadata, __pycache__) are never
# deleted remotely, so mirroring over a git clone leaves its .git intact.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)" || { printf 'not inside a git checkout\n' >&2; exit 1; }

die() { printf '%s\n' "$*" >&2; exit 1; }

HOST=""
KEY_FILE=""
DRY_RUN=""
DEST="/var/tmp/secure-single-server"
usage() {
  printf 'usage: %s --host USER@HOST [--key KEYFILE] [--dest REMOTE_DIR] [--dry-run]\n' "${0##*/}"
  exit 2
}
while [[ $# -gt 0 ]]; do
  if [[ "$1" == "--dry-run" ]]; then DRY_RUN=yes; shift; continue; fi
  [[ $# -ge 2 ]] || usage
  case "$1" in
    --host) HOST="$2" ;;
    --key) KEY_FILE="$2" ;;
    --dest) DEST="$2" ;;
    *) usage ;;
  esac
  shift 2
done
[[ -n "${HOST}" ]] || usage
# rsync --delete runs against this value, so it must be a real, specific
# directory: absolute, at least two segments, and no . or .. segments -
# "/" or "/home" would erase every remote file the local tree lacks.
[[ "${DEST}" =~ ^/([A-Za-z0-9._-]+/)+[A-Za-z0-9._-]+$ ]] \
  || die 'destination must be an absolute path of at least two plain segments'
if [[ "${DEST}" =~ /(\.|\.\.)(/|$) ]]; then
  die 'destination must not contain . or .. segments'
fi
# The key path is joined into one string for rsync -e, which splits it on
# whitespace; spaces or quotes would corrupt the ssh command.
case "${KEY_FILE}" in
  *[[:space:]]* | *\'* | *\"*) die 'key file path must not contain whitespace or quotes' ;;
esac
command -v rsync >/dev/null || die 'rsync is not installed on this workstation'

# Seeded non-empty so Bash 3.2 with nounset can expand them.
rsync_opts=(-av --delete)
[[ -z "${DRY_RUN}" ]] || rsync_opts+=(--dry-run)
ssh_opts=(-o BatchMode=yes)
[[ -z "${KEY_FILE}" ]] || ssh_opts+=(-i "${KEY_FILE}")

# Fail before transferring anything if connectivity is wrong.
ssh "${ssh_opts[@]}" "${HOST}" true || die "cannot reach ${HOST}"

# The trailing slash on the source is load-bearing: it means "the contents
# of the checkout", so the destination mirrors it directly. Without it,
# rsync nests the checkout one directory deeper on every run. The
# destination's trailing slash is cosmetic.
rsync "${rsync_opts[@]}" \
  --exclude .git --exclude .DS_Store --exclude __pycache__ \
  -e "ssh ${ssh_opts[*]}" \
  "${ROOT}/" "${HOST}:${DEST}/"

if [[ -n "${DRY_RUN}" ]]; then
  printf 'dry run complete: no changes transferred\n'
else
  printf 'sync complete: %s/ -> %s:%s/ (working tree, mirror)\n' "${ROOT}" "${HOST}" "${DEST}"
fi
