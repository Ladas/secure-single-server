#!/usr/bin/env bash
# One bounded PR-review turn inside an existing review-github sandbox.
set -euo pipefail
H_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../scripts/harness-lib.sh
# shellcheck disable=SC1091
source "${H_DIR}/../../scripts/harness-lib.sh"
NAME="opencode-review-github"
REPO=""
MESSAGE=""
TIMEOUT=3600
PRS=()
while [[ $# -gt 0 ]]; do
  [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || die "missing value for $1"
  case "$1" in
    --name) NAME="$2" ;;
    --repo) REPO="$2" ;;
    --pr) [[ "$2" =~ ^[0-9]+$ ]] || die "--pr must be a pull-request number"; PRS+=("#$2") ;;
    --message) MESSAGE="$2" ;;
    --timeout) TIMEOUT="$2" ;;
    *) die "unknown arg: $1" ;;
  esac
  shift 2
done
[[ "${NAME}" =~ ^[a-zA-Z0-9][a-zA-Z0-9-]*$ ]] || die 'invalid sandbox name'
[[ "${REPO}" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || die '--repo must be OWNER/REPO'
[[ "${#PRS[@]}" -gt 0 ]] || die 'provide at least one --pr N'
if [[ ! "${TIMEOUT}" =~ ^[1-9][0-9]{0,4}$ ]] || (( TIMEOUT > 14400 )); then
  die 'timeout must be 1..14400 seconds'
fi
# Instructions and the task travel through stdin, not interpolated commands.
harness_ssh "${NAME}" 'mkdir -p ~/review ~/reports'
harness_ssh "${NAME}" 'cat > ~/review/AGENTS.md' <"${H_DIR}/review-agents.md"
{
  printf 'Review pull requests %s of the GitHub repository %s.\n' \
    "$(IFS=,; echo "${PRS[*]}")" "${REPO}"
  printf 'Follow AGENTS.md in this directory exactly: fetch each PR, analyze it, and write one report per PR under ~/reports.\n'
  if [[ -n "${MESSAGE//[[:space:]]/}" ]]; then
    printf 'Additional instructions from the operator:\n%s\n' "${MESSAGE}"
  fi
} | harness_ssh "${NAME}" 'cat > ~/review/task.md'
# The message is read from the file by the remote shell; no local quoting of task text.
# shellcheck disable=SC2016 # the command substitution runs remotely, inside the sandbox
review_cmd='cd ~/review && opencode run --format json "$(cat task.md)"'
if command -v timeout >/dev/null 2>&1; then
  timeout "${TIMEOUT}" harness_ssh "${NAME}" "${review_cmd}"
else
  harness_ssh "${NAME}" "${review_cmd}"
fi
note "Review turn finished; collect reports with: ${H_DIR}/collect.sh --name ${NAME}"
