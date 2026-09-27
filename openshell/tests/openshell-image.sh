#!/usr/bin/env bash
# Health check for the suite-owned fixture; lifecycle belongs to runtime.sh.
set -euo pipefail
: "${OPENSHELL_BIN:=/usr/local/bin/openshell}"
systemctl --user is-active --quiet openshell-gateway.service
curl --fail --silent http://127.0.0.1:8091/healthz >/dev/null
"${OPENSHELL_BIN}" sandbox list --output json >/dev/null
printf 'openshell-image: fixture service, health and CLI OK\n'
