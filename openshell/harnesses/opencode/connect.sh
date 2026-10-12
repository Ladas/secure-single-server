#!/usr/bin/env bash
set -euo pipefail
H_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../scripts/harness-lib.sh
# shellcheck disable=SC1091
source "${H_DIR}/../../scripts/harness-lib.sh"
NAME="opencode-dev"
if [[ $# -gt 0 ]]; then
  [[ $# -ge 2 && "$1" == "--name" ]] || die 'usage: connect.sh [--name NAME] [COMMAND...]'
  NAME="$2"
  shift 2
fi
if [[ $# -eq 0 ]]; then
  harness_connect_tty "${NAME}" opencode
else
  harness_connect_tty "${NAME}" "$@"
fi
