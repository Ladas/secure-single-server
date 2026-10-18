#!/usr/bin/env bash
set -euo pipefail
H_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../../../scripts/common/lib.sh
# shellcheck disable=SC1091
source "${H_DIR}/../../../../scripts/common/lib.sh"

NAME=opencode-pr-queue
REPO=""
LABEL=bot
STATE=""
MESSAGE=""
INTERVAL=300
TIMEOUT=3600
MAX_PAGES=10
MAX_ISSUES_PER_POLL=1
ONCE=0
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: watch.sh --name NAME --repo OWNER/REPO --state PATH
                 [--label LABEL] [--message TEXT] [--interval SECONDS]
                 [--timeout SECONDS] [--max-pages PAGES]
                 [--max-issues-per-poll COUNT] [--once] [--dry-run]

Polls public GitHub issues carrying LABEL and queues eligible issues while
preventing duplicate active turns. The watcher uses no GitHub credentials and
still leaves patch publication to a human reviewer.
EOF
}

while [[ $# -gt 0 ]]; do
  argument="$1"
  case "${argument}" in
    --help|-h)
      usage
      exit 0
      ;;
    --name|--repo|--label|--state|--message|--interval|--timeout|--max-pages|--max-issues-per-poll)
      [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || die "missing value for ${argument}"
      case "${argument}" in
        --name) NAME="$2" ;;
        --repo) REPO="$2" ;;
        --label) LABEL="$2" ;;
        --state) STATE="$2" ;;
        --message) MESSAGE="$2" ;;
        --interval) INTERVAL="$2" ;;
        --timeout) TIMEOUT="$2" ;;
        --max-pages) MAX_PAGES="$2" ;;
        --max-issues-per-poll) MAX_ISSUES_PER_POLL="$2" ;;
      esac
      shift 2
      ;;
    --once)
      ONCE=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    *)
      usage >&2
      die "unknown argument: ${argument}"
      ;;
  esac
done

[[ "${NAME}" =~ ^[a-zA-Z0-9][a-zA-Z0-9-]*$ ]] || die 'invalid sandbox name'
[[ "${REPO}" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] \
  || die 'repository must use OWNER/REPO'
[[ "${REPO}" != *..* ]] || die 'repository name must not contain ".."'
[[ ${#LABEL} -ge 1 && ${#LABEL} -le 100 && "${LABEL}" != *$'\n'* ]] \
  || die 'label must be one line of at most 100 characters'
[[ "${STATE}" == /* && -n "${STATE##*/}" ]] || die 'state must be an absolute file path'
[[ "${STATE##*/}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] \
  || die 'state file name must contain only letters, numbers, dots, dashes, and underscores'
case "${STATE}" in
  */../*|*/..) die 'state path must be canonical' ;;
esac
[[ "${MESSAGE}" != *$'\n'* && ${#MESSAGE} -le 4096 ]] \
  || die 'message must be one line of at most 4096 characters'
[[ "${INTERVAL}" =~ ^[0-9]+$ ]] || die 'interval must be an integer from 60 through 86400'
(( INTERVAL >= 60 && INTERVAL <= 86400 )) || die 'interval must be an integer from 60 through 86400'
[[ "${TIMEOUT}" =~ ^[1-9][0-9]{1,4}$ ]] || die 'timeout must be an integer from 60 through 14400'
(( TIMEOUT >= 60 && TIMEOUT <= 14400 )) || die 'timeout must be an integer from 60 through 14400'
[[ "${MAX_PAGES}" =~ ^[1-9][0-9]{0,3}$ ]] || die 'max-pages must be an integer from 1 through 100'
(( MAX_PAGES >= 1 && MAX_PAGES <= 100 )) || die 'max-pages must be an integer from 1 through 100'
[[ "${MAX_ISSUES_PER_POLL}" =~ ^[1-9][0-9]{0,2}$ ]] \
  || die 'max-issues-per-poll must be an integer from 1 through 100'
(( MAX_ISSUES_PER_POLL >= 1 && MAX_ISSUES_PER_POLL <= 100 )) \
  || die 'max-issues-per-poll must be an integer from 1 through 100'

require_command curl
require_command python3
[[ -x "${H_DIR}/queue.sh" ]] || die 'PR queue runner is missing or not executable'
[[ -f "${H_DIR}/completion-marker.py" ]] || die 'completion marker helper is missing'

state_directory="$(dirname -- "${STATE}")"
[[ -d "${state_directory}" && -w "${state_directory}" ]] \
  || die "state directory must already exist and be writable: ${state_directory}"
if ! STATE="$(
  python3 - "${STATE}" <<'PY'
import stat
import os
import sys
from pathlib import Path

requested = Path(sys.argv[1])
if not requested.is_absolute() or ".." in requested.parts:
    raise SystemExit("state path must be absolute and canonical")
requested_parent = requested.parent
try:
    directory = requested_parent.resolve(strict=True)
except OSError:
    raise SystemExit("state directory must already exist")
if directory != requested_parent:
    raise SystemExit("state parent must be canonical and must not contain symlinks")
if not directory.is_dir():
    raise SystemExit("state parent is not a directory")
if directory.stat().st_uid != os.geteuid():
    raise SystemExit("state parent is not owned by the current user")
for component in (directory, *directory.parents):
    mode = stat.S_IMODE(component.stat().st_mode)
    if mode & 0o022 and not mode & stat.S_ISVTX:
        raise SystemExit(f"refusing unsafe state directory component: {component}")
print(directory / requested.name)
PY
)"; then
  die "could not validate state path: ${STATE}"
fi
[[ ! -L "${STATE}" ]] || die "refusing symlinked watcher state file: ${STATE}"
[[ ! -d "${STATE}" ]] || die "state path is a directory: ${STATE}"
fetch_page() {  # <page-number>
  local page_file header_file curl_transport result
  page_file="$(mktemp)"
  header_file="$(mktemp)"
  if curl_transport="$(
    curl --fail --silent --show-error --location --max-time 20 \
    --header 'Accept: application/vnd.github+json' \
    --header 'User-Agent: secure-single-server-opencode-pr-queue-watch' \
    --output "${page_file}" \
    --dump-header "${header_file}" \
    --write-out $'HTTP_STATUS=%{http_code}\nCONTENT_TYPE=%{content_type}' \
    --get \
    --data-urlencode "labels=${LABEL}" \
    --data 'state=open' \
    --data 'per_page=100' \
    --data "page=$1" \
    --data 'sort=created' \
    --data 'direction=asc' \
    "https://api.github.com/repos/${REPO}/issues"
  )"; then
    if python3 -c '
import re
import json
import sys

page_path = sys.argv[1]
header_path = sys.argv[2]
transport = sys.argv[3]
label = sys.argv[4]
repository = sys.argv[5]
lines = transport.splitlines()
if (len(lines) != 2 or not lines[0].startswith("HTTP_STATUS=") or
        not lines[1].startswith("CONTENT_TYPE=")):
    raise SystemExit("GitHub issue response is missing transport metadata")
if lines[0] != "HTTP_STATUS=200":
    raise SystemExit("GitHub issue poll did not return HTTP 200")
if not lines[1].removeprefix("CONTENT_TYPE=").startswith("application/json"):
    raise SystemExit("GitHub issue poll did not return JSON")
try:
    with open(header_path, encoding="iso-8859-1") as headers:
        link_headers = [
            line.split(":", 1)[1].strip()
            for line in headers.read().splitlines()
            if line.lower().startswith("link:")
        ]
except OSError:
    raise SystemExit("GitHub returned an unreadable response header")
has_next_page = any(
    re.search(r"<[^>]+>;\s*rel=(\"next\"|next)", link_header)
    for link_header in link_headers
)
try:
    with open(page_path, encoding="utf-8") as page:
        issues = json.load(page)
except (json.JSONDecodeError, UnicodeDecodeError):
    raise SystemExit("GitHub returned invalid issue JSON")
if not isinstance(issues, list):
    raise SystemExit("GitHub issue response must be a JSON array")
if any(not isinstance(issue, dict) for issue in issues):
    raise SystemExit("GitHub issue response contains an invalid item")
print(f"PAGE_COUNT={len(issues)} HAS_NEXT_PAGE={int(has_next_page)}")

for issue in issues:
    state = issue.get("state")
    number = issue.get("number")
    issue_id = issue.get("id")
    repository_url = issue.get("repository_url")
    html_url = issue.get("html_url")
    labels_value = issue.get("labels")
    pull_request = issue.get("pull_request")
    # GitHub resolves OWNER/REPO case-insensitively but reports the canonical
    # spelling, so compare the reported URLs without regard to case.
    canonical_repository = repository.lower()
    expected_repository_url = f"https://api.github.com/repos/{canonical_repository}"
    expected_html_url = (
        f"https://github.com/{canonical_repository}/pull/{number}"
        if isinstance(pull_request, dict) else
        f"https://github.com/{canonical_repository}/issues/{number}"
    )
    if (state not in ("open", "closed") or
            not isinstance(number, int) or isinstance(number, bool) or number <= 0 or
            not isinstance(issue_id, int) or isinstance(issue_id, bool) or issue_id <= 0 or
            not isinstance(repository_url, str) or
            repository_url.lower() != expected_repository_url or
            not isinstance(html_url, str) or html_url.lower() != expected_html_url or
            not isinstance(labels_value, list) or
            any(not isinstance(item, dict) or not isinstance(item.get("name"), str)
                for item in labels_value) or
            (pull_request is not None and not isinstance(pull_request, dict))):
        raise SystemExit("GitHub issue response contains an invalid issue")
    labels_value = issue.get("labels", [])
    labels = [
        item.get("name")
        for item in labels_value
    ]
    if state == "open" and pull_request is None and label in labels:
        print(f"{issue_id} {number}")
' "${page_file}" "${header_file}" "${curl_transport}" "${LABEL}" "${REPO}"
    then
      result=0
    else
      result=$?
    fi
  else
    result=$?
  fi
  rm -f "${page_file}" "${header_file}"
  return "${result}"
}

state_operation() {  # <validate|status|reserve|complete|release> <issue> <lease-seconds> <token>
  python3 - "${STATE}" "${REPO}" "${LABEL}" "$1" "$2" "$3" "$4" <<'PY'
import fcntl
import json
import math
import os
import secrets
import stat
import sys
import time
import tempfile
from pathlib import Path

if len(sys.argv) != 8:
    raise SystemExit("state operation requires exactly seven arguments")
state_path = Path(sys.argv[1])
repository = sys.argv[2]
label = sys.argv[3]
operation = sys.argv[4]
if operation not in {"validate", "status", "reserve", "complete", "release"}:
    raise SystemExit(f"unknown watcher state operation: {operation}")
if not sys.argv[5].isdigit() or not sys.argv[6].isdigit():
    raise SystemExit("state operation issue and lease values must be integers")
issue_number = int(sys.argv[5])
lease_seconds = int(sys.argv[6])
lease_token = sys.argv[7]
lock_path = Path(f"{state_path}.lock")
maximum_attempted_issues = 10000
maximum_lease_seconds = 18000
if operation == "validate":
    if issue_number != 0 or lease_seconds != 0 or lease_token:
        raise SystemExit("validate does not accept issue, lease, or token values")
elif operation == "status":
    if issue_number <= 0 or lease_seconds != 0 or lease_token:
        raise SystemExit("status requires an issue but no lease or token")
elif operation == "reserve":
    if (issue_number <= 0 or not 60 <= lease_seconds <= maximum_lease_seconds or
            lease_token):
        raise SystemExit("reserve requires an issue and a bounded lease duration")
else:
    if issue_number <= 0 or lease_seconds != 0 or not lease_token:
        raise SystemExit(f"{operation} requires an issue and token but no lease")
current_uid = os.geteuid()
no_follow = getattr(os, "O_NOFOLLOW", None)
if no_follow is None:
    raise SystemExit("platform does not support safe watcher file opening")

state_parent = state_path.parent
try:
    resolved_state_parent = state_parent.resolve(strict=True)
except OSError:
    raise SystemExit(f"state directory must exist: {state_parent}")
if resolved_state_parent != state_parent:
    raise SystemExit(f"state parent must remain canonical: {state_parent}")
for component in (state_parent, *state_parent.parents):
    component_status = component.stat()
    if (not stat.S_ISDIR(component_status.st_mode) or
            stat.S_IMODE(component_status.st_mode) & 0o022 and
            not stat.S_IMODE(component_status.st_mode) & stat.S_ISVTX):
        raise SystemExit(f"refusing unsafe state directory component: {component}")

try:
    lock_descriptor = os.open(
        lock_path,
        os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NONBLOCK | no_follow,
        0o600)
    created_lock = True
except FileExistsError:
    lock_descriptor = os.open(
        lock_path, os.O_RDWR | os.O_NONBLOCK | no_follow)
    created_lock = False
try:
    lock_status = os.fstat(lock_descriptor)
    if (not stat.S_ISREG(lock_status.st_mode) or
            lock_status.st_uid != current_uid or
            stat.S_IMODE(lock_status.st_mode) & 0o077):
        raise SystemExit(f"refusing unsafe watcher lock file: {lock_path}")
    lock_identity = (lock_status.st_dev, lock_status.st_ino)
    if created_lock:
        os.fchmod(lock_descriptor, 0o600)
    fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
    try:
        locked_status = os.lstat(lock_path)
    except OSError:
        raise SystemExit(f"watcher lock file disappeared: {lock_path}")
    if ((locked_status.st_dev, locked_status.st_ino) != lock_identity or
            not stat.S_ISREG(locked_status.st_mode) or
            locked_status.st_uid != current_uid or
            stat.S_IMODE(locked_status.st_mode) & 0o077):
        raise SystemExit(f"refusing changed watcher lock file: {lock_path}")
    state_identity = None

    if os.path.lexists(state_path):
        try:
            final_status = os.lstat(state_path)
        except OSError:
            raise SystemExit(f"could not inspect watcher state file: {state_path}")
        if not stat.S_ISREG(final_status.st_mode):
            raise SystemExit(f"refusing non-regular watcher state file: {state_path}")
        state_descriptor = os.open(state_path, os.O_RDONLY | no_follow)
        try:
            state_status = os.fstat(state_descriptor)
            if ((state_status.st_dev, state_status.st_ino) !=
                    (final_status.st_dev, final_status.st_ino)):
                raise SystemExit(
                    f"watcher state file changed while it was opened: {state_path}")
            if (not stat.S_ISREG(state_status.st_mode) or
                    state_status.st_uid != current_uid or
                    stat.S_IMODE(state_status.st_mode) & 0o077):
                raise SystemExit(f"refusing unsafe watcher state file: {state_path}")
            state_identity = (state_status.st_dev, state_status.st_ino)
            with os.fdopen(state_descriptor) as state_file:
                state_descriptor = None
                try:
                    state = json.load(state_file)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    raise SystemExit(f"could not read watch state: {state_path}")
        finally:
            if state_descriptor is not None:
                os.close(state_descriptor)
    else:
        state = {
            "version": 2,
            "repository": repository,
            "label": label,
            "attempted_issues": [],
            "in_progress_issues": {},
        }

    if (not isinstance(state, dict) or state.get("version") not in (1, 2) or
            not isinstance(state.get("repository"), str) or
            state["repository"].lower() != repository.lower() or
            state.get("label") != label):
        raise SystemExit(f"watch state does not match this repository and label: {state_path}")
    if state.get("version") == 1 and "in_progress_issues" in state:
        raise SystemExit(f"invalid legacy in_progress_issues value in watch state: {state_path}")
    expected_fields = {
        "version", "repository", "label", "attempted_issues",
    }
    if state.get("version") == 2:
        expected_fields.add("in_progress_issues")
    if set(state) != expected_fields:
        raise SystemExit(f"invalid watcher state fields: {state_path}")
    attempted = state.get("attempted_issues")
    if (not isinstance(attempted, list) or
            any(not isinstance(number, int) or isinstance(number, bool) or number <= 0
                for number in attempted)):
        raise SystemExit(f"invalid attempted_issues value in watch state: {state_path}")
    if (len(attempted) != len(set(attempted)) or
            len(attempted) > maximum_attempted_issues):
        raise SystemExit(f"invalid attempted_issues count in watch state: {state_path}")
    if state.get("version") == 1:
        if "in_progress_issues" in state:
            raise SystemExit(f"invalid legacy in_progress_issues value in watch state: {state_path}")
        in_progress = {}
    else:
        in_progress = state.get("in_progress_issues")
        if not isinstance(in_progress, dict):
            raise SystemExit(f"invalid in_progress_issues value in watch state: {state_path}")
    now = time.time()
    for key, entry in in_progress.items():
        if (not key.isdigit() or int(key) <= 0 or not isinstance(entry, dict) or
                not isinstance(entry.get("lease_owner"), str) or
                not entry.get("lease_owner") or
                not isinstance(entry.get("lease_expires_at"), (int, float)) or
                isinstance(entry.get("lease_expires_at"), bool) or
                not math.isfinite(entry.get("lease_expires_at")) or
                entry.get("lease_expires_at") <= 0 or
                entry.get("lease_expires_at") > now + maximum_lease_seconds + 60):
            raise SystemExit(f"invalid in_progress_issues value in watch state: {state_path}")
    if set(attempted).intersection(int(key) for key in in_progress):
        raise SystemExit(f"overlapping issue state in watch state: {state_path}")
    legacy_state = state.get("version") == 1

    if issue_number in attempted:
        print("attempted" if operation in {"status", "reserve"} else "already-attempted")
        raise SystemExit(0)

    state = {
        "version": 2,
        "repository": repository,
        "label": label,
        "attempted_issues": attempted,
        "in_progress_issues": in_progress,
    }
    issue_key = str(issue_number)

    expired_keys = [
        key for key, entry in in_progress.items()
        if entry["lease_expires_at"] <= now
    ]
    for key in expired_keys:
        del in_progress[key]

    def write_state():
        global state_identity
        def sync_state_directory():
            directory_descriptor = os.open(
                str(state_path.parent), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)

        try:
            current_lock_status = os.lstat(lock_path)
        except OSError:
            raise SystemExit(f"watcher lock file disappeared: {lock_path}")
        if ((current_lock_status.st_dev, current_lock_status.st_ino) != lock_identity or
                not stat.S_ISREG(current_lock_status.st_mode) or
                current_lock_status.st_uid != current_uid or
                stat.S_IMODE(current_lock_status.st_mode) & 0o077):
            raise SystemExit(f"refusing changed watcher lock file: {lock_path}")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{state_path.name}.", suffix=".tmp", dir=str(state_path.parent))
        try:
            with os.fdopen(descriptor, "w") as temporary:
                json.dump(state, temporary, indent=2, sort_keys=True)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            os.chmod(temporary_name, 0o600)
            if os.path.lexists(state_path):
                try:
                    current_status = os.lstat(state_path)
                except OSError:
                    raise SystemExit(f"watcher state disappeared: {state_path}")
                if ((current_status.st_dev, current_status.st_ino) != state_identity or
                        not stat.S_ISREG(current_status.st_mode) or
                        current_status.st_uid != current_uid or
                        stat.S_IMODE(current_status.st_mode) & 0o077):
                    raise SystemExit(f"refusing changed watcher state file: {state_path}")
                os.replace(temporary_name, state_path)
                sync_state_directory()
            else:
                try:
                    os.link(temporary_name, state_path)
                except FileExistsError:
                    raise SystemExit(f"watch state appeared unexpectedly: {state_path}")
                except OSError as error:
                    raise SystemExit(
                        f"could not create watcher state file: {state_path}: {error}")
                created_status = os.lstat(state_path)
                state_identity = (
                    created_status.st_dev, created_status.st_ino)
                os.unlink(temporary_name)
                sync_state_directory()
        except BaseException:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

    if state_identity is None or expired_keys or legacy_state:
        write_state()

    if operation == "validate":
        print("valid")
        raise SystemExit(0)

    if operation == "status":
        entry = in_progress.get(issue_key)
        if entry and entry["lease_expires_at"] > now:
            print("in-progress")
        else:
            print("available")
        raise SystemExit(0)

    if operation == "reserve":
        entry = in_progress.get(issue_key)
        if entry and entry["lease_expires_at"] > time.time():
            print("in-progress")
            raise SystemExit(0)
        if len(attempted) >= maximum_attempted_issues:
            raise SystemExit(f"watch state is full: {state_path}")
        lease_owner = secrets.token_hex(16)
        lease_expires_at = time.time() + lease_seconds
        in_progress[issue_key] = {
            "lease_owner": lease_owner,
            "lease_expires_at": lease_expires_at,
        }
        write_state()
        print(f"reserved:{lease_owner}:{int(lease_expires_at)}")
        raise SystemExit(0)

    if operation == "complete":
        entry = in_progress.get(issue_key)
        if not entry or entry["lease_owner"] != lease_token:
            print("lost")
            raise SystemExit(0)
        del in_progress[issue_key]
        state["attempted_issues"] = attempted + [issue_number]
        write_state()
        print("completed")
        raise SystemExit(0)

    if operation == "release":
        entry = in_progress.get(issue_key)
        if entry and entry["lease_owner"] == lease_token:
            del in_progress[issue_key]
            write_state()
            print("released")
        else:
            print("lost")
        raise SystemExit(0)

    raise SystemExit(f"unknown watcher state operation: {operation}")
finally:
    os.close(lock_descriptor)
PY
}

state_operation validate 0 0 "" >/dev/null || die 'could not validate watcher state'
ISSUES_QUEUED_THIS_POLL=0

run_queue_turn() {  # <absolute-deadline> <queue-command...>
  local absolute_deadline="$1"; shift
  python3 - "${absolute_deadline}" "$@" <<'PY'
import os
import signal
import subprocess
import sys
import time

timeout_seconds = float(sys.argv[1]) - time.time()
command = sys.argv[2:]
if timeout_seconds <= 0 or not command:
    raise SystemExit("invalid bounded queue turn")
try:
    process = subprocess.Popen(
        command, stdin=subprocess.DEVNULL, start_new_session=True)
except OSError as error:
    print(f"could not start the OpenCode queue turn: {error}", file=sys.stderr)
    raise SystemExit(125)
try:
    process.wait(timeout=timeout_seconds)
except subprocess.TimeoutExpired:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
    print("OpenCode queue turn exceeded the watcher deadline", file=sys.stderr)
    raise SystemExit(124)
raise SystemExit(process.returncode)
PY
}

process_issue() {  # <issue-number>
  local issue="$1" status_result reservation lease_token lease_expiry queue_deadline completion_file completion_token completion_result marker_present queue_status
  [[ "${issue}" =~ ^[1-9][0-9]{0,8}$ ]] || die "invalid GitHub issue number: ${issue}"

  if ! status_result="$(state_operation status "${issue}" 0 "")"; then
    die "could not inspect watcher state for issue #${issue}"
  fi
  completion_file="${STATE}.issue-${issue}.complete"
  completion_token=""
  marker_present=0
  if ((!DRY_RUN)) && [[ -e "${completion_file}" ]]; then
    [[ -f "${completion_file}" && ! -L "${completion_file}" ]] \
      || die "invalid completion marker for issue #${issue}: ${completion_file}"
    marker_present=1
    # The watcher creates this marker empty before the queue turn starts, and the
    # turn writes its lease token only after success. An empty or unreadable
    # marker therefore means the turn is still pending, while a readable token
    # proves that the turn succeeded.
    completion_token="$(
      python3 "${H_DIR}/completion-marker.py" read "${completion_file}" 2>/dev/null || true)"
  fi
  if [[ "${status_result}" == attempted ]]; then
    if ((marker_present)); then
      die "completion marker remains for already-attempted issue #${issue}; inspect it manually: ${completion_file}"
    fi
    note "Issue #${issue} was already attempted; skipping"
    return 0
  fi
  if [[ "${status_result}" == in-progress ]]; then
    if [[ -n "${completion_token}" ]]; then
      if ! completion_result="$(state_operation complete "${issue}" 0 "${completion_token}")"; then
        die "could not reconcile completion marker for issue #${issue}: ${completion_file}"
      fi
      if [[ "${completion_result}" == completed ]]; then
        python3 "${H_DIR}/completion-marker.py" remove "${completion_file}" \
          || die "could not remove the reconciled completion marker for issue #${issue}: ${completion_file}"
        note "Recovered completion state for issue #${issue}"
        return 0
      fi
      die "completion marker for issue #${issue} no longer matches its lease: ${completion_file}"
    fi
    note "Issue #${issue} is being processed by another watcher; skipping"
    return 0
  fi
  [[ "${status_result}" == available ]] \
    || die "unexpected watcher status result for issue #${issue}"

  if ((DRY_RUN)); then
    note "Would queue issue #${issue}"
    return 0
  fi

  local -a preflight_arguments=(
    --name "${NAME}"
    --repo "${REPO}"
    --issue "${issue}"
    --timeout "${TIMEOUT}"
  )
  if [[ -n "${MESSAGE}" ]]; then
    preflight_arguments+=(--message "${MESSAGE}")
  fi
  if ! "${H_DIR}/queue.sh" "${preflight_arguments[@]}" --preflight; then
    note "Preflight failed for issue #${issue}; continuing with later issues"
    return 2
  fi

  python3 "${H_DIR}/completion-marker.py" validate "${completion_file}" \
    || die "invalid completion marker for issue #${issue}: ${completion_file}"
  if ((marker_present)) && [[ -n "${completion_token}" ]]; then
    if ! completion_result="$(state_operation complete "${issue}" 0 "${completion_token}")"; then
      die "could not reconcile completion marker for issue #${issue}: ${completion_file}"
    fi
    if [[ "${completion_result}" == completed ]]; then
      python3 "${H_DIR}/completion-marker.py" remove "${completion_file}" \
        || die "could not remove the reconciled completion marker for issue #${issue}: ${completion_file}"
      note "Recovered completion state for issue #${issue}"
      return 0
    fi
    die "completion marker for issue #${issue} no longer matches a live lease; inspect it manually: ${completion_file}"
  fi

  reservation="$(state_operation reserve "${issue}" "$((TIMEOUT + 600))" "")" \
    || die "could not reserve issue #${issue}"
  if [[ "${reservation}" == attempted ]]; then
    note "Issue #${issue} was already attempted; skipping"
    return 0
  fi
  if [[ "${reservation}" == in-progress ]]; then
    note "Issue #${issue} is being processed by another watcher; skipping"
    return 0
  fi
  [[ "${reservation}" == reserved:* ]] || die "unexpected watcher state result for issue #${issue}"
  lease_token="${reservation#reserved:}"
  lease_expiry="${lease_token##*:}"
  lease_token="${lease_token%:*}"
  [[ "${lease_token}" =~ ^[a-f0-9]{32}$ && "${lease_expiry}" =~ ^[1-9][0-9]{9,10}$ ]] \
    || die "invalid watcher reservation for issue #${issue}"
  queue_deadline=$((lease_expiry - 300))
  ISSUES_QUEUED_THIS_POLL=$((ISSUES_QUEUED_THIS_POLL + 1))

  if [[ -e "${completion_file}" || -L "${completion_file}" ]]; then
    # This watcher holds the only live lease, so an empty or unreadable marker
    # left by an interrupted turn cannot belong to another active worker.
    python3 "${H_DIR}/completion-marker.py" remove "${completion_file}" \
      || die "could not discard the stale completion marker for issue #${issue}: ${completion_file}"
    note "Discarded a stale completion marker for issue #${issue}"
  fi

  local -a queue_arguments=(
    --name "${NAME}"
    --repo "${REPO}"
    --issue "${issue}"
    --timeout "${TIMEOUT}"
    --completion-file "${completion_file}"
    --completion-token "${lease_token}"
  )
  if [[ -n "${MESSAGE}" ]]; then
    queue_arguments+=(--message "${MESSAGE}")
  fi
  if ! python3 "${H_DIR}/completion-marker.py" create "${completion_file}"; then
    if ! state_operation release "${issue}" 0 "${lease_token}" >/dev/null; then
      die "could not create the completion marker or release issue #${issue}: ${completion_file}"
    fi
    die "could not create the completion marker for issue #${issue}: ${completion_file}"
  fi

  queue_status=0
  run_queue_turn "${queue_deadline}" "${H_DIR}/queue.sh" "${queue_arguments[@]}" \
    || queue_status=$?
  if ((queue_status)); then
    note "OpenCode queue turn failed for issue #${issue}"
    if ((queue_status == 125)); then
      python3 "${H_DIR}/completion-marker.py" remove "${completion_file}" \
        || die "could not remove the marker after a queue-start failure for issue #${issue}: ${completion_file}"
      state_operation release "${issue}" 0 "${lease_token}" >/dev/null \
        || die "could not release issue #${issue} after a queue-start failure"
      note "Issue #${issue} lease released after a queue-start failure"
      return 1
    fi
    if completion_token="$(
      python3 "${H_DIR}/completion-marker.py" read "${completion_file}" 2>/dev/null)"; then
      [[ "${completion_token}" == "${lease_token}" ]] \
        || die "queue turn returned an invalid completion marker for issue #${issue}"
      if ! completion_result="$(state_operation complete "${issue}" 0 "${completion_token}")"; then
        die "could not reconcile a valid completion marker for issue #${issue}: ${completion_file}"
      fi
      if [[ "${completion_result}" == completed ]]; then
        python3 "${H_DIR}/completion-marker.py" remove "${completion_file}" \
          || die "could not remove the reconciled completion marker for issue #${issue}: ${completion_file}"
        note "Recovered completion state after a failed queue turn for issue #${issue}"
        return 0
      fi
      die "completion marker for issue #${issue} no longer matches its lease; inspect it manually: ${completion_file}"
    else
      if python3 "${H_DIR}/completion-marker.py" remove "${completion_file}" 2>/dev/null; then
        note "Issue #${issue} lease retained until expiry; remote work may still be stopping"
      else
        die "unsafe completion marker retained for issue #${issue}: ${completion_file}"
      fi
    fi
    return 1
  fi

  if ! completion_token="$(
    python3 "${H_DIR}/completion-marker.py" read "${completion_file}")"; then
    if status_result="$(state_operation status "${issue}" 0 "")" &&
       [[ "${status_result}" == attempted ]]; then
      note "Completion marker for issue #${issue} was reconciled by another watcher"
      return 0
    fi
    die "could not read the completion marker for issue #${issue}; lease and completion marker retained: ${completion_file}"
  fi
  [[ "${completion_token}" == "${lease_token}" ]] \
    || die "queue turn returned an invalid completion marker for issue #${issue}"

  if ! completion_result="$(state_operation complete "${issue}" 0 "${lease_token}")"; then
    die "could not update watcher state for issue #${issue}; lease and completion marker retained: ${completion_file}"
  fi
  if [[ "${completion_result}" == lost ]]; then
    die "issue #${issue} lease expired while processing; completion marker retained: ${completion_file}"
  fi
  if [[ "${completion_result}" == completed ]]; then
    python3 "${H_DIR}/completion-marker.py" remove "${completion_file}" \
      || die "could not remove the completion marker for issue #${issue}: ${completion_file}"
  elif [[ "${completion_result}" == already-attempted ]]; then
    if [[ -e "${completion_file}" || -L "${completion_file}" ]]; then
      python3 "${H_DIR}/completion-marker.py" remove "${completion_file}" \
        || die "could not remove the reconciled completion marker for issue #${issue}: ${completion_file}"
    fi
    note "Completion marker for issue #${issue} was reconciled by another watcher"
    return 0
  else
    die "unexpected watcher state result for issue #${issue}"
  fi
  note "Completed PR-candidate turn for issue #${issue}"
}

poll_issues() {
  local page=1 page_output page_issues page_header page_count has_next_page issue_id issue_number issue
  local process_status
  local -a candidates=()
  local -A seen_issue_ids=() seen_issue_numbers=()
  ISSUES_QUEUED_THIS_POLL=0
  while ((page <= MAX_PAGES)); do
    if ! page_output="$(fetch_page "${page}")"; then
      note "GitHub issue poll failed; retrying in ${INTERVAL} seconds"
      return 1
    fi

    page_header="${page_output%%$'\n'*}"
    read -r page_count has_next_page <<<"${page_header#PAGE_COUNT=}"
    [[ "${page_count}" =~ ^[0-9]+$ && "${has_next_page}" =~ ^HAS_NEXT_PAGE=[01]$ ]] \
      || die 'GitHub issue filter returned invalid pagination metadata'
    ((page_count <= 100)) || die 'GitHub issue filter returned an invalid page count'
    has_next_page="${has_next_page#HAS_NEXT_PAGE=}"
    if [[ "${page_output}" == *$'\n'* ]]; then
      page_issues="${page_output#*$'\n'}"
    else
      page_issues=""
    fi

    while IFS=' ' read -r issue_id issue_number; do
      [[ -n "${issue_id}" ]] || continue
      [[ "${issue_id}" =~ ^[1-9][0-9]{0,18}$ ]] \
        || die 'GitHub issue filter returned an invalid issue ID'
      [[ "${issue_number}" =~ ^[1-9][0-9]{0,8}$ ]] \
        || die 'GitHub issue filter returned an invalid issue number'
      if [[ -n "${seen_issue_ids[${issue_id}]+x}" ]]; then
        note "GitHub issue pagination returned duplicate issue ID ${issue_id}; retrying"
        return 1
      fi
      if [[ -n "${seen_issue_numbers[${issue_number}]+x}" ]]; then
        note "GitHub issue pagination returned duplicate issue #${issue_number}; retrying"
        return 1
      fi
      seen_issue_ids["${issue_id}"]=1
      seen_issue_numbers["${issue_number}"]=1
      candidates+=("${issue_number}")
    done <<<"${page_issues}"

    if ((page == MAX_PAGES && has_next_page)); then
      note "GitHub issue pagination reached --max-pages ${MAX_PAGES}; later issues may remain pending"
      break
    fi
    ((has_next_page)) || break
    ((page++))
  done

  for issue in "${candidates[@]}"; do
    if ((ISSUES_QUEUED_THIS_POLL >= MAX_ISSUES_PER_POLL)); then
      note "Reached --max-issues-per-poll ${MAX_ISSUES_PER_POLL}; remaining issues stay pending"
      break
    fi
    process_status=0
    process_issue "${issue}" || process_status=$?
    if ((process_status == 2 && !ONCE)); then
      continue
    fi
    if ((process_status)); then
      if ((ONCE)); then
        return 1
      fi
      note "The failed issue will be retried on the next poll"
      return 0
    fi
  done
}

while true; do
  if ! poll_issues; then
    if ((ONCE)); then
      exit 1
    fi
  fi
  if ((ONCE)); then
    break
  fi
  sleep "${INTERVAL}"
done
