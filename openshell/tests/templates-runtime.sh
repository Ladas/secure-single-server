#!/usr/bin/env bash
# Run as the gateway owner on a disposable installed host; no model key needed.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
first="$("${ROOT}/openshell/scripts/template.sh" sync)"
second="$("${ROOT}/openshell/scripts/template.sh" sync)"
[[ -n "${first}" && "${first}" == "${second}" ]] || {
  printf 'template sync changed names on an unchanged catalog\n' >&2
  exit 1
}
printf 'Actual gateway template sync and exact readback passed twice\n'
