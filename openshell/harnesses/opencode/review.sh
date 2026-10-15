#!/usr/bin/env bash
# One bounded PR-review turn inside an existing pr-review sandbox.
set -euo pipefail
H_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../scripts/harness-lib.sh
# shellcheck disable=SC1091
source "${H_DIR}/../../scripts/harness-lib.sh"
NAME="opencode-pr-review"
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
# Each turn starts from a clean workspace: stale metadata, branches, or clones
# from earlier runs would mislead the agent (and reports stay untouched).
harness_ssh "${NAME}" 'rm -rf ~/review && mkdir -p ~/review ~/reports'
harness_ssh "${NAME}" 'cat > ~/AGENTS.md' <"${H_DIR}/review-agents.md"
{
  printf 'Review pull requests %s of the GitHub repository %s.\n' \
    "$(IFS=,; echo "${PRS[*]}")" "${REPO}"
  printf 'Your home directory is /sandbox. Follow /sandbox/AGENTS.md exactly: fetch each PR, analyze it, and write one report per PR under /sandbox/reports.\n'
  if [[ -n "${MESSAGE//[[:space:]]/}" ]]; then
    printf 'Additional instructions from the operator:\n%s\n' "${MESSAGE}"
  fi
} | harness_ssh "${NAME}" 'cat > ~/review/task.md'
# The message is read from the file by the remote shell; no local quoting of task text.
# opencode run drains piped stdin to EOF before submitting its prompt, and the SSH
# channel's stdin never EOFs while review.sh runs non-interactively, so the turn
# must close stdin itself or it hangs before creating a session. The turn runs
# from the sandbox home so ~/review and ~/reports both stay inside the opencode
# project: tool calls outside it are auto-rejected and abort the run.
# shellcheck disable=SC2016 # the command substitution runs remotely, inside the sandbox
review_cmd='cd ~ && opencode run --format json "$(cat ~/review/task.md)" </dev/null'
if command -v timeout >/dev/null 2>&1; then
  # timeout execs a command, so the harness_ssh shell function must be
  # re-imported by a child bash; export the function and its variables.
  export OPENSHELL_BIN OPENSHELL_GATEWAY_NAME OPENSHELL_SANDBOX_USER
  export -f _os _proxy_cmd harness_ssh
  # shellcheck disable=SC2016 # $1/$2 are the child bash's positional parameters
  timeout "${TIMEOUT}" bash -c 'harness_ssh "$1" "$2"' _ "${NAME}" "${review_cmd}"
else
  harness_ssh "${NAME}" "${review_cmd}"
fi
note "Review turn finished; collect reports with: ${H_DIR}/collect.sh --name ${NAME}"
