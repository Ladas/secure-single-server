#!/usr/bin/env bash
set -euo pipefail
H_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../scripts/harness-lib.sh
# shellcheck disable=SC1091
source "${H_DIR}/../../scripts/harness-lib.sh"
NAME="openclaw-dev"
if [[ $# -gt 0 ]]; then
  if [[ "$1" == "--name" ]]; then
    [[ $# -ge 2 ]] || die 'usage: connect.sh [--name NAME] [COMMAND...]'
    NAME="$2"
    shift 2
  fi
fi
# Service command and authentication are not qualified for this pinned image.
if [[ $# -eq 0 ]]; then
  harness_connect_tty "${NAME}"
else
  harness_connect_tty "${NAME}" "$@"
fi
