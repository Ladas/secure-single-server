#!/usr/bin/env bash
set -euo pipefail
H_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../scripts/harness-lib.sh
# shellcheck disable=SC1091
source "${H_DIR}/../../scripts/harness-lib.sh"
NAME="openclaw-dev"
[[ "${1:-}" == "--name" ]] && NAME="$2"
# Service command and authentication are not qualified for this pinned image.
harness_connect_tty "${NAME}"
