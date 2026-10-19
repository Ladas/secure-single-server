#!/usr/bin/env bash
# Collect PR-review reports from a sandbox over the SSH stdin/stdout channel.
set -euo pipefail
H_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../scripts/harness-lib.sh
# shellcheck disable=SC1091
source "${H_DIR}/../../scripts/harness-lib.sh"
NAME="opencode-pr-review"
DEST=""
# Reports are Markdown written by one turn; anything near this is a malfunction
# or a hostile sandbox, not a review.
MAX_KB=10240
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
require_command python3

# Extract into staging, never straight into DEST: reports already sitting in
# DEST would otherwise make an empty collection look like a successful one.
staging="$(mktemp -d)"
trap 'rm -rf "${staging}"' EXIT
out="${staging}/out"
mkdir -p "${out}"
max_bytes=$(( MAX_KB * 1024 ))
# The sandbox is the untrusted side of this channel and chooses what it sends.
# extract-safe-tar.py refuses non-regular members and unsafe paths and bounds
# the bytes it will write, so a runaway or hostile archive cannot fill the
# workstation or escape the staging directory.
harness_ssh "${NAME}" 'tar cf - -C ~/reports .' </dev/null \
  | python3 "${H_DIR}/../../scripts/extract-safe-tar.py" "${out}" \
     --max-file-bytes "${max_bytes}" --max-total-bytes "${max_bytes}" \
  || die "collecting from sandbox ${NAME} failed or exceeded the ${MAX_KB} KiB limit"

# Only plain pr-N.md files may reach DEST.
reports=()
while IFS= read -r -d '' entry; do
  rel="${entry#"${out}/"}"
  [[ "${rel}" =~ ^pr-[0-9]+\.md$ ]] \
    || die "unexpected entry in collected reports: ${rel}"
  reports+=("${rel}")
done < <(find "${out}" -mindepth 1 -print0)
(( ${#reports[@]} > 0 )) \
  || die "no reports produced in sandbox ${NAME}; the review turn may not have run"

mkdir -p "${DEST}"
for report in "${reports[@]}"; do
  cp -p "${staging}/out/${report}" "${DEST}/${report}"
done
printf 'Collected %d report(s) into %s:\n' "${#reports[@]}" "${DEST}"
printf '%s\n' "${reports[@]/#/${DEST}/}"
