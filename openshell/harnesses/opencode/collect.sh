#!/usr/bin/env bash
# Collect PR-review reports from a sandbox over the SSH stdin/stdout channel.
set -euo pipefail
H_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../scripts/harness-lib.sh
# shellcheck disable=SC1091
source "${H_DIR}/../../scripts/harness-lib.sh"
NAME="opencode-pr-review"
DEST=""
while [[ $# -gt 0 ]]; do
  [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || die "missing value for $1"
  case "$1" in
    --name) NAME="$2" ;;
    --dest) DEST="$2" ;;
    *) die "unknown arg: $1" ;;
  esac
  shift 2
done
[[ "${NAME}" =~ ^[a-zA-Z0-9][a-zA-Z0-9-]*$ ]] || die 'invalid sandbox name'
DEST="${DEST:-${NAME}-reports}"
mkdir -p "${DEST}"
# Byte-transparent tar over the same channel that installed the harness config.
harness_ssh "${NAME}" 'tar cf - -C ~/reports .' | tar xf - -C "${DEST}"
collected="$(find "${DEST}" -type f | sort)"
if [[ -z "${collected}" ]]; then
  die "no report files found in ${DEST}; the review turn may not have run"
fi
printf 'Collected reports into %s:\n%s\n' "${DEST}" "${collected}"
