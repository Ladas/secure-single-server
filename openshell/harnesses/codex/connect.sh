#!/usr/bin/env bash
set -euo pipefail
H_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../scripts/harness-lib.sh
# shellcheck disable=SC1091
source "${H_DIR}/../../scripts/harness-lib.sh"
NAME="codex-dev"
if [[ $# -gt 0 ]]; then
  if [[ "$1" == "--name" ]]; then
    [[ $# -ge 2 ]] || die 'usage: connect.sh [--name NAME] [--] [COMMAND...]'
    NAME="$2"
    [[ "${NAME}" =~ ^[a-zA-Z0-9][a-zA-Z0-9-]*$ && ${#NAME} -le 19 ]] \
      || die 'invalid sandbox name'
    shift 2
  fi
fi
if [[ "${1:-}" == "--" ]]; then
  shift
fi
[[ "${NAME}" =~ ^[a-zA-Z0-9][a-zA-Z0-9-]*$ && ${#NAME} -le 19 ]] \
  || die 'invalid sandbox name'
if [[ $# -eq 0 ]]; then
  harness_connect_tty "${NAME}" codex
else
  harness_connect_tty "${NAME}" "$@"
fi
