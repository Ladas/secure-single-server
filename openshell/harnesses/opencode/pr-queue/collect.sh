#!/usr/bin/env bash
set -euo pipefail
H_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../scripts/harness-lib.sh
# shellcheck disable=SC1091
source "${H_DIR}/../../../scripts/harness-lib.sh"
# shellcheck disable=SC1091
source "${H_DIR}/lib.sh"

NAME=opencode-pr-queue
DEST=./opencode-pr-queue-artifacts

while [[ $# -gt 0 ]]; do
  argument="$1"
  case "${argument}" in
    --name|--dest)
      [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || die "missing value for ${argument}"
      case "${argument}" in
        --name) NAME="$2" ;;
        --dest) DEST="$2" ;;
      esac
      shift 2
      ;;
    *)
      die "unknown argument: ${argument}"
      ;;
  esac
done

[[ "${NAME}" =~ ^[a-zA-Z0-9][a-zA-Z0-9-]*$ ]] || die 'invalid sandbox name'
[[ -n "${DEST}" ]] || die 'destination cannot be empty'
[[ ! -e "${DEST}" ]] || die "destination already exists: ${DEST}"
require_command python3

harness_ssh "${NAME}" "test -d \"\$HOME/pr-queue/artifacts\"" </dev/null \
  || die 'no PR queue artifact directory exists'
task_list="$(harness_ssh "${NAME}" \
  "cd \"\$HOME/pr-queue/artifacts\" && find . -mindepth 1 -maxdepth 1 -type d -print" \
  </dev/null)"
[[ -n "${task_list}" ]] || die 'no PR queue task directories were produced'

while IFS= read -r task; do
  task="${task#./}"
  [[ "${task}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] \
    || die "invalid PR queue task directory name: ${task}"
  for artifact in metadata.json report.md; do
    harness_ssh "${NAME}" \
      "test -s \"\$HOME/pr-queue/artifacts/${task}/${artifact}\"" \
      </dev/null \
      || die "task ${task} did not produce non-empty ${artifact}"
  done

  if ! metadata_status="$(
    harness_ssh "${NAME}" "cat \"\$HOME/pr-queue/artifacts/${task}/metadata.json\"" \
      </dev/null | read_metadata_status
  )"; then
    die "task ${task} produced invalid metadata"
  fi

  if [[ "${metadata_status}" == success ]]; then
    harness_ssh "${NAME}" \
      "test -s \"\$HOME/pr-queue/artifacts/${task}/changes.patch\"" \
      </dev/null \
      || die "successful task ${task} did not produce non-empty changes.patch"
  elif harness_ssh "${NAME}" \
      "test -e \"\$HOME/pr-queue/artifacts/${task}/changes.patch\"" \
      </dev/null; then
    harness_ssh "${NAME}" \
      "test -s \"\$HOME/pr-queue/artifacts/${task}/changes.patch\"" \
      </dev/null \
      || die "failed task ${task} produced an empty changes.patch"
  fi
done <<<"${task_list}"

mkdir -p "${DEST}"
chmod 0755 "${DEST}"
# Keep repository symlinks out of the archive while retaining regular files and
# directories needed for review.
# shellcheck disable=SC2016
archive_command='cd "$HOME/pr-queue/artifacts" &&
  archive_list="$(mktemp)" &&
  trap '\''rm -f "$archive_list"'\'' EXIT &&
  find . \( -type d -o -type f \) -print0 >"$archive_list" &&
  tar --null --no-recursion -cf - -T "$archive_list"'
harness_ssh "${NAME}" "${archive_command}" </dev/null \
  | python3 "${H_DIR}/../../../scripts/extract-safe-tar.py" "${DEST}"

file_count="$(cd "${DEST}" && find . -type f | wc -l | tr -d '[:space:]')"
[[ "${file_count}" =~ ^[0-9]+$ ]] || die 'could not count collected files'
note "Collected ${file_count} files to ${DEST}"
