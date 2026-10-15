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
# Setup calls move a few KiB each; a minute is generous and still bounded.
SETUP_TIMEOUT=120
PRS=()
PR_NUMS=()
while [[ $# -gt 0 ]]; do
  [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || die "missing value for $1"
  case "$1" in
    --name) NAME="$2" ;;
    --repo) REPO="$2" ;;
    --pr) [[ "$2" =~ ^[0-9]+$ ]] || die "--pr must be a pull-request number"
          PRS+=("#$2"); PR_NUMS+=("$2") ;;
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

# timeout execs a command, so the harness_ssh shell function must be
# re-imported by a child bash; export the function and its variables once.
export OPENSHELL_BIN OPENSHELL_GATEWAY_NAME OPENSHELL_SANDBOX_USER
export -f _os _proxy_cmd harness_ssh
# A stalled SSH channel is a known failure mode for this harness (see
# docs/development/review-turn-stdin-hang.md), so every call carries a
# deadline, not only the turn.
bounded() {  # <seconds> <sandbox> <cmd>; stdin is forwarded to the remote
  if command -v timeout >/dev/null 2>&1; then
    # shellcheck disable=SC2016 # $1/$2 are the child bash's positional parameters
    timeout "$1" bash -c 'harness_ssh "$1" "$2"' _ "$2" "$3"
  else
    harness_ssh "$2" "$3"
  fi
}

# Instructions and the task travel through stdin, not interpolated commands.
# Each turn starts from a clean workspace: stale metadata, branches, or clones
# from earlier runs would mislead the agent. Reports for other PRs survive, but
# the ones this run is about must not -- a turn that fails before writing would
# otherwise leave collect.sh returning the previous run's report as this one's.
stale_reports=""
for pr_num in "${PR_NUMS[@]}"; do
  stale_reports+=" ~/reports/pr-${pr_num}.md"
done
bounded "${SETUP_TIMEOUT}" "${NAME}" \
  "rm -rf ~/review && mkdir -p ~/review ~/reports && rm -f${stale_reports}"
bounded "${SETUP_TIMEOUT}" "${NAME}" 'cat > ~/AGENTS.md' <"${H_DIR}/review-agents.md"
{
  printf 'Review pull requests %s of the GitHub repository %s.\n' \
    "$(IFS=,; echo "${PRS[*]}")" "${REPO}"
  printf 'Your home directory is /sandbox. Follow /sandbox/AGENTS.md exactly: fetch each PR, analyze it, and write one report per PR under /sandbox/reports.\n'
  if [[ -n "${MESSAGE//[[:space:]]/}" ]]; then
    printf 'Additional instructions from the operator:\n%s\n' "${MESSAGE}"
  fi
} | bounded "${SETUP_TIMEOUT}" "${NAME}" 'cat > ~/review/task.md'
# The message is read from the file by the remote shell; no local quoting of task text.
# opencode run drains piped stdin to EOF before submitting its prompt, and the SSH
# channel's stdin never EOFs while review.sh runs non-interactively, so the turn
# must close stdin itself or it hangs before creating a session. The turn runs
# from the sandbox home so ~/review and ~/reports both stay inside the opencode
# project: tool calls outside it are auto-rejected and abort the run.
# shellcheck disable=SC2016 # the command substitution runs remotely, inside the sandbox
turn='opencode run --format json "$(cat ~/review/task.md)" </dev/null'
# A host-side timeout kills only the local ssh: the remote opencode survives as
# a zombie turn still holding gateway reservations and rate-limit slots, which
# starves later runs. Bound it inside the sandbox too, and keep the host
# deadline as the backstop for a channel that stalls before the turn starts.
# The host waits slightly longer so the sandbox's own deadline reports first.
review_cmd="cd ~ && if command -v timeout >/dev/null 2>&1; then"
review_cmd+=" timeout -k 30 ${TIMEOUT} ${turn}; else ${turn}; fi"
bounded "$(( TIMEOUT + 60 ))" "${NAME}" "${review_cmd}"
note "Review turn finished; collect reports with: ${H_DIR}/collect.sh --name ${NAME}"
