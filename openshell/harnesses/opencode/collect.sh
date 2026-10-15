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

# Extract into staging, never straight into DEST: reports already sitting in
# DEST would otherwise make an empty collection look like a successful one.
# (PR #55 adds openshell/scripts/extract-safe-tar.py for the same job; collapse
# this onto it when the two branches reconcile.)
staging="$(mktemp -d)"
trap 'rm -rf "${staging}"' EXIT
tarball="${staging}/reports.tar"
max_bytes=$(( MAX_KB * 1024 ))
# The sandbox is the untrusted side of this channel and chooses what it sends,
# so head caps what can land here rather than letting a runaway archive fill
# the workstation. Byte-transparent tar over the same channel that installed
# the harness config.
status=0
harness_ssh "${NAME}" 'tar cf - -C ~/reports .' | head -c "${max_bytes}" >"${tarball}" \
  || status=$?
(( $(wc -c <"${tarball}") < max_bytes )) \
  || die "sandbox reports exceed the ${MAX_KB} KiB limit"
(( status == 0 )) || die "collecting from sandbox ${NAME} failed (exit ${status})"
mkdir -p "${staging}/out"
tar xf "${tarball}" -C "${staging}/out"

# Only plain pr-N.md files may reach DEST. A symlink or a nested path chosen by
# the sandbox would otherwise be written wherever it pointed.
reports=()
while IFS= read -r -d '' entry; do
  rel="${entry#"${staging}/out/"}"
  [[ -f "${entry}" && ! -L "${entry}" ]] \
    || die "refusing non-regular entry in collected reports: ${rel}"
  [[ "${rel}" =~ ^pr-[0-9]+\.md$ ]] \
    || die "unexpected entry in collected reports: ${rel}"
  reports+=("${rel}")
done < <(find "${staging}/out" -mindepth 1 -print0)
(( ${#reports[@]} > 0 )) \
  || die "no reports produced in sandbox ${NAME}; the review turn may not have run"

mkdir -p "${DEST}"
for report in "${reports[@]}"; do
  cp -p "${staging}/out/${report}" "${DEST}/${report}"
done
printf 'Collected %d report(s) into %s:\n' "${#reports[@]}" "${DEST}"
printf '%s\n' "${reports[@]/#/${DEST}/}"
