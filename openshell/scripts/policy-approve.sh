#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./harness-lib.sh
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/harness-lib.sh"

: "${OPENSHELL_APPROVAL_AUDIT_FILE:=/var/lib/openshell/approvals.jsonl}"

usage() {
  cat <<'EOF'
usage: policy-approve.sh enable <sandbox>
       policy-approve.sh list <sandbox>
       policy-approve.sh approve <sandbox> --chunk-id <id> [--yes]
       policy-approve.sh reject <sandbox> --chunk-id <id> --reason <text>

Approves an OpenShell network-rule proposal for the current sandbox instance.
The grant is not written to a profile policy file and resets on recreation.
EOF
}

_strip_ansi() {
  python3 -c 'import re,sys; sys.stdout.write(re.sub(r"\x1b\[[0-9;]*m", "", sys.stdin.read()))'
}

_validate_audit_target() {  # <file>
  python3 - "$1" <<'PY'
import os
import stat
import sys

path = sys.argv[1]
parent = os.path.dirname(path)
if not os.path.isdir(parent):
    raise SystemExit(f"audit directory does not exist: {parent}")
if not os.path.exists(path):
    raise SystemExit(0)
mode = os.stat(path).st_mode
if not stat.S_ISREG(mode):
    raise SystemExit(f"audit target is not a regular file: {path}")
if stat.S_IMODE(mode) & 0o077:
    raise SystemExit(f"audit file permissions are too broad: {path}")
PY
}

_append_audit_record() {  # <file> <sandbox> <chunk-id>
  python3 - "$1" "$2" "$3" <<'PY'
import datetime
import fcntl
import json
import os
import pwd
import stat
import sys

path, sandbox, chunk_id = sys.argv[1:]
flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
if hasattr(os, "O_NOFOLLOW"):
    flags |= os.O_NOFOLLOW
descriptor = os.open(path, flags, 0o600)
try:
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        raise SystemExit(f"audit target is not a regular file: {path}")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise SystemExit(f"audit file permissions are too broad: {path}")
    with os.fdopen(descriptor, "a", encoding="utf-8") as audit:
        descriptor = -1
        fcntl.flock(audit.fileno(), fcntl.LOCK_EX)
        record = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds"),
            "event": "openshell.endpoint_grant.approved",
            "sandbox": sandbox,
            "chunk_id": chunk_id,
            "operator": pwd.getpwuid(os.getuid()).pw_name,
            "grant_lifetime": "sandbox_instance",
            "reset_on_recreate": True,
        }
        audit.write(json.dumps(record, separators=(",", ":")) + "\n")
        audit.flush()
        os.fsync(audit.fileno())
finally:
    if descriptor >= 0:
        os.close(descriptor)
PY
}

[[ $# -ge 1 ]] || { usage >&2; exit 1; }
command="$1"
shift

case "${command}" in
  enable|list)
    [[ $# -eq 1 ]] || { usage >&2; die "${command} takes exactly one sandbox name"; }
    sandbox="$1"
    ;;
  approve|reject)
    [[ $# -ge 1 ]] || { usage >&2; die "${command} requires a sandbox name"; }
    sandbox="$1"
    shift
    chunk_id=""
    reason=""
    assume_yes=no
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --chunk-id)
          [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || die "missing value for --chunk-id"
          chunk_id="$2"; shift 2;;
        --reason)
          [[ $# -ge 2 && -n "$2" ]] || die "missing value for --reason"
          reason="$2"; shift 2;;
        --yes)
          assume_yes=yes; shift;;
        *)
          die "unknown argument: $1";;
      esac
    done
    ;;
  *)
    usage >&2
    die "unknown command: ${command}"
    ;;
esac

[[ "${sandbox}" =~ ^[a-zA-Z0-9][a-zA-Z0-9-]*$ ]] || die "invalid sandbox name"
require_command python3

case "${command}" in
  enable)
    harness_enable_policy_advisor "${sandbox}"
    note "Policy advisor enabled for sandbox ${sandbox}"
    ;;
  list)
    _os rule get "${sandbox}" --status pending
    ;;
  approve)
    [[ -n "${chunk_id}" ]] || die "approve requires --chunk-id"
    [[ "${chunk_id}" =~ ^[a-zA-Z0-9][a-zA-Z0-9._:-]+$ ]] || die "invalid chunk id"
    _validate_audit_target "${OPENSHELL_APPROVAL_AUDIT_FILE}"
    pending="$(_os rule get "${sandbox}" --status pending | _strip_ansi)"
    printf '%s\n' "${pending}"
    printf '%s\n' "${pending}" | awk -v id="${chunk_id}" \
      '$1 == "Chunk:" && $2 == id {found=1} END {exit !found}' \
      || die "pending chunk not found: ${chunk_id}"

    if [[ "${assume_yes}" != yes ]]; then
      printf 'Type APPROVE to grant this endpoint for the current sandbox instance: '
      read -r confirmation
      [[ "${confirmation}" == APPROVE ]] || die "approval cancelled"
    fi

    _os rule approve "${sandbox}" --chunk-id "${chunk_id}"
    _append_audit_record "${OPENSHELL_APPROVAL_AUDIT_FILE}" "${sandbox}" "${chunk_id}"
    note "Endpoint grant approved for sandbox ${sandbox}; it resets on recreation"
    note "Approval audit: ${OPENSHELL_APPROVAL_AUDIT_FILE}"
    ;;
  reject)
    [[ -n "${chunk_id}" ]] || die "reject requires --chunk-id"
    [[ -n "${reason}" ]] || die "reject requires --reason"
    [[ "${chunk_id}" =~ ^[a-zA-Z0-9][a-zA-Z0-9._:-]+$ ]] || die "invalid chunk id"
    _os rule reject "${sandbox}" --chunk-id "${chunk_id}" --reason "${reason}"
    note "Endpoint proposal rejected for sandbox ${sandbox}"
    ;;
esac
