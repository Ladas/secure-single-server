#!/usr/bin/env bash
# Install one profile on a disposable RHEL host with synthetic provider secrets.
set -euo pipefail

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly REPO_DIR
# shellcheck source=scripts/common/lib.sh
source "${REPO_DIR}/scripts/common/lib.sh"

usage() {
  printf 'usage: sudo bash tests/rhel/install-smoke.sh all-in-one|remote-gateway memory|valkey [MATERIAL_DIR]\n'
  printf 'Remote MATERIAL_DIR must contain tls.pem, tls-key.pem and jwt-public.pem.\n'
}

if [[ "${1:-}" == --help ]]; then usage; exit 0; fi
[[ "$#" -ge 2 && "$#" -le 3 ]] || { usage >&2; exit 2; }
scenario=$1
profile=$2
case "$scenario" in
  all-in-one) [[ "$#" -eq 2 ]] || die 'all-in-one takes no TLS material directory' ;;
  remote-gateway) [[ "$#" -eq 3 ]] || die 'remote-gateway requires its TLS/public JWT material directory' ;;
  *) die 'scenario must be all-in-one or remote-gateway; OpenShell is a later test stage' ;;
esac
case "$profile" in
  memory|valkey) ;;
  *) die 'profile must be memory or valkey' ;;
esac

require_root
# Never switch profiles, overwrite credentials, or repair a partial install here.
for path in "$PROFILE_FILE" "$MANIFEST_FILE" "$SCENARIO_FILE" "$CONFIG_DIR/shared-gateway.yaml"; do
  [[ ! -e "$path" && ! -L "$path" ]] || die "existing installation material: $path; inspect it before continuing"
done

options=(--profile "$profile")
if [[ "$scenario" == remote-gateway ]]; then
  material=$3
  for file in tls.pem tls-key.pem jwt-public.pem; do
    [[ -f "$material/$file" && -r "$material/$file" ]] || die "missing or unreadable material: $material/$file"
  done
  options+=(--tls-cert "$material/tls.pem" --tls-key "$material/tls-key.pem"
    --jwt-public-key "$material/jwt-public.pem")
fi

installer="$REPO_DIR/scripts/$scenario/install"
"$installer" --prepare
# A new version makes failures/retries visible without touching existing secrets.
version="smoke-$(date -u +%Y%m%dT%H%M%S)-$$"
printf '%s' synthetic-openai | "$REPO_DIR/scripts/common/secret-set" openai "$version"
printf '%s' synthetic-anthropic | "$REPO_DIR/scripts/common/secret-set" anthropic "$version"
options+=(--openai-secret "praxis-openai-api-key-$version"
  --anthropic-secret "praxis-anthropic-api-key-$version")

if [[ "$profile" == valkey ]]; then
  "$REPO_DIR/scripts/common/secret-set" valkey "$version" --generate
  options+=(--valkey-image docker.io/valkey/valkey@sha256:63346cb24a61221e76bdf41acce99b3968a9fa83d8122144deab45394b27b4f2
    --valkey-url-secret "praxis-valkey-url-$version" --valkey-acl-secret "praxis-valkey-acl-$version")
fi

"$installer" "${options[@]}"
"$REPO_DIR/scripts/common/status"
"$REPO_DIR/scripts/common/verify" --host
printf 'PASS: %s/%s installation and host checks; inference has not been tested.\n' "$scenario" "$profile"
printf 'Installed profile and synthetic secrets remain for SSH logout/reboot checks. No automatic uninstall.\n'
