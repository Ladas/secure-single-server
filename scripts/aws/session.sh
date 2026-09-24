#!/usr/bin/env bash
# Source from the repository root in Bash or zsh. No cloud calls on load.
# Call functions in `if` or `||` guards, including when the caller has errexit.

if [ ! -f scripts/aws/rhel-vm ]; then
  printf 'Run from the reviewed secure-single-server repository root.\n' >&2
  return 1
fi
AWS_TEST_REPO="$PWD"

_aws_test_error() {
  printf 'error: %s\n' "$*" >&2
  return 1
}

_aws_test_prompt() {
  if [ ! -t 0 ]; then
    _aws_test_error 'Credential prompts require an interactive terminal; do not pipe input.'
    return 1
  fi
  printf '%s: ' "$2" >&2
  if IFS= read -r -s "$1"; then
    printf '\n' >&2
  else
    printf '\n' >&2
    _aws_test_error 'Input cancelled; no credentials loaded.'
    return 1
  fi
}

aws_test_credentials() {
  set +x
  set +a
  local test_access='' test_secret='' test_token=''
  unset AWS_TEST_CREDENTIALS AWS_TEST_READY AWS_TEST_PLAN_INPUTS ALL_IN_ONE_HOST REMOTE_HOST
  unset AWS_PROFILE AWS_DEFAULT_PROFILE AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
  _aws_test_prompt test_access 'AWS access key ID' || return 1
  if [ -z "$test_access" ]; then
    _aws_test_error 'Access key ID is required; rerun the credential step.'
    return 1
  fi
  _aws_test_prompt test_secret 'AWS secret access key' || return 1
  if [ -z "$test_secret" ]; then
    _aws_test_error 'Secret access key is required; rerun the credential step.'
    return 1
  fi
  _aws_test_prompt test_token 'AWS session token (Enter for long-lived IAM keys)' || return 1
  export AWS_ACCESS_KEY_ID="$test_access" AWS_SECRET_ACCESS_KEY="$test_secret"
  if [ -n "$test_token" ]; then export AWS_SESSION_TOKEN="$test_token"; fi
  export AWS_PAGER=''
  AWS_TEST_CREDENTIALS=ready
  printf 'Credentials loaded in this terminal only; not yet validated against AWS.\n'
}

_aws_test_identity_ready() {
  if [ "${AWS_TEST_CREDENTIALS:-}" != ready ] || [ -z "${AWS_ACCESS_KEY_ID:-}" ] ||
      [ -z "${AWS_SECRET_ACCESS_KEY:-}" ]; then
    _aws_test_error 'Load credentials first.'
    return 1
  fi
  if [ -z "${REGION:-}" ] || [ -z "${RUN_PREFIX:-}" ]; then
    _aws_test_error 'Run the settings block first.'
    return 1
  fi
}

aws_test_discover() {
  local test_tool test_identity test_principal test_subnets test_ip test_subnet test_cidr
  unset AWS_TEST_READY AWS_TEST_PLAN_INPUTS ACCOUNT ALL_IN_ONE_HOST REMOTE_HOST
  _aws_test_identity_ready || return 1
  for test_tool in aws python3 jq curl ssh ssh-keygen; do
    command -v "$test_tool" >/dev/null 2>&1 || {
      _aws_test_error "Install missing prerequisite: $test_tool"
      return 1
    }
  done
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || {
    _aws_test_error 'Python 3.9 or newer is required.'
    return 1
  }
  test_identity=$(aws --region "$REGION" sts get-caller-identity --output json) || return 1
  ACCOUNT=$(printf '%s' "$test_identity" | jq -er '.Account | select(test("^[0-9]{12}$"))') || return 1
  test_principal=$(printf '%s' "$test_identity" | jq -er '.Arn') || return 1
  case "$test_principal" in
    *:root) _aws_test_error 'Root-account credentials are refused.'; return 1 ;;
  esac
  printf 'AWS account: %s\nPrincipal: %s\n' "$ACCOUNT" "$test_principal"
  test_subnet=${SUBNET:-}
  if [ -z "$test_subnet" ]; then
    test_subnets=$(aws --region "$REGION" ec2 describe-subnets \
      --filters Name=default-for-az,Values=true Name=state,Values=available \
        "Name=owner-id,Values=$ACCOUNT" --output json) || return 1
    test_subnet=$(printf '%s' "$test_subnets" | jq -er '
      .Subnets | map(select(.AvailableIpAddressCount > 0)) |
      sort_by(.AvailabilityZone, .SubnetId) | .[0].SubnetId //
      error("No available default subnet. Set SUBNET to an approved public subnet.")') || return 1
  fi
  test_cidr=${CLIENT_CIDR:-}
  if [ -z "$test_cidr" ]; then
    test_ip=$(curl -4 -fsS --connect-timeout 5 --max-time 10 https://checkip.amazonaws.com) || return 1
    test_cidr="$test_ip/32"
  fi
  test_cidr=$(python3 -c '
import ipaddress, sys
try:
    network = ipaddress.ip_network(sys.argv[1], strict=True)
    if network.version != 4 or network.prefixlen != 32:
        raise ValueError("not an IPv4 host")
except ValueError:
    sys.exit("Allowed source must be one IPv4 /32; check CLIENT_CIDR or IP detection.")
print(network)' "$test_cidr") || return 1
  SUBNET="$test_subnet"
  CLIENT_CIDR="$test_cidr"
  AWS_TEST_READY=ready
  printf 'Region: %s\nSubnet: %s\nAllowed source: %s\nSSH key: %s\nRun prefix: %s\n' \
    "$REGION" "$SUBNET" "$CLIENT_CIDR" "${SSH_KEY:-not set}" "$RUN_PREFIX"
}

aws_test_key() {
  local test_key_dir
  case "${SSH_KEY:-}" in
    /*) ;;
    *) _aws_test_error 'Set SSH_KEY to an absolute path in a dedicated private directory.'; return 1 ;;
  esac
  if [ -e "$SSH_KEY" ] || [ -L "$SSH_KEY" ] || [ -e "$SSH_KEY.pub" ] || [ -L "$SSH_KEY.pub" ]; then
    _aws_test_error 'Key path already exists; nothing overwritten. Choose a new SSH_KEY, or reuse your existing test key at the plan step.'
    return 1
  fi
  test_key_dir=$(dirname "$SSH_KEY") || return 1
  case "$test_key_dir" in
    /|"${HOME:-}"|"$AWS_TEST_REPO")
      _aws_test_error 'Use a dedicated key directory, not a filesystem, home or repository root.'
      return 1 ;;
  esac
  install -d -m 0700 "$test_key_dir" || return 1
  ssh-keygen -t ed25519 -f "$SSH_KEY" -C "${RUN_PREFIX:-secure-single-server-test}" || return 1
  chmod 0600 "$SSH_KEY" || return 1
  printf 'Private test key: %s\nOnly %s.pub will be imported.\n' "$SSH_KEY" "$SSH_KEY"
}

_aws_test_inputs() {
  printf '%s\n' "${REGION:-}" "${ACCOUNT:-}" "${SUBNET:-}" "${CLIENT_CIDR:-}" \
    "${RUN_PREFIX:-}" "${SSH_KEY:-}" "${ARCH:-}" "${INSTANCE_TYPE:-}"
}

_aws_test_args() {
  _aws_test_identity_ready || return 1
  if [ "${AWS_TEST_READY:-}" != ready ] || [ -z "${ACCOUNT:-}" ] ||
      [ -z "${SUBNET:-}" ] || [ -z "${CLIENT_CIDR:-}" ] ||
      [ -z "${SSH_KEY:-}" ] || [ -z "${ARCH:-}" ]; then
    _aws_test_error 'Complete settings and successful discovery before planning or applying.'
    return 1
  fi
  AWS_TEST_ARGS=(--region "$REGION" --account-id "$ACCOUNT" --subnet-id "$SUBNET"
    --public-key "$SSH_KEY.pub" --allowed-cidr "$CLIENT_CIDR" --arch "$ARCH")
  if [ -n "${INSTANCE_TYPE:-}" ]; then AWS_TEST_ARGS+=(--instance-type "$INSTANCE_TYPE"); fi
}

_aws_test_vm() {
  python3 "$AWS_TEST_REPO/scripts/aws/rhel-vm" "$@"
}

aws_test_plan() {
  local test_scenario
  unset AWS_TEST_PLAN_INPUTS
  _aws_test_args || return 1
  for test_scenario in all-in-one remote-gateway; do
    _aws_test_vm plan "${AWS_TEST_ARGS[@]}" --scenario "$test_scenario" \
      --prefix "$RUN_PREFIX-$test_scenario" \
      --state-file "$AWS_TEST_REPO/.state/$RUN_PREFIX-$test_scenario.json" || return 1
  done
  AWS_TEST_PLAN_INPUTS=$(_aws_test_inputs)
  printf 'Both read-only plans passed. Review them before the separate apply step.\n'
}

aws_test_apply() {
  local test_scenario
  _aws_test_args || return 1
  if [ -z "${AWS_TEST_PLAN_INPUTS:-}" ] || [ "$AWS_TEST_PLAN_INPUTS" != "$(_aws_test_inputs)" ]; then
    _aws_test_error 'Run and review successful plans with these settings before applying.'
    return 1
  fi
  # A partial apply must not be silently retried by pasting this command again.
  unset AWS_TEST_PLAN_INPUTS
  for test_scenario in all-in-one remote-gateway; do
    _aws_test_vm apply "${AWS_TEST_ARGS[@]}" --scenario "$test_scenario" \
      --prefix "$RUN_PREFIX-$test_scenario" \
      --state-file "$AWS_TEST_REPO/.state/$RUN_PREFIX-$test_scenario.json" || return 1
  done
}

aws_test_verify() {
  local test_all_info test_remote_info test_all_ip test_remote_ip
  unset ALL_IN_ONE_HOST REMOTE_HOST
  _aws_test_identity_ready || return 1
  if [ -z "${ACCOUNT:-}" ]; then _aws_test_error 'Discover or set the recorded account first.'; return 1; fi
  test_all_info=$(_aws_test_vm verify --region "$REGION" --account-id "$ACCOUNT" \
    --state-file "$AWS_TEST_REPO/.state/$RUN_PREFIX-all-in-one.json") || return 1
  test_remote_info=$(_aws_test_vm verify --region "$REGION" --account-id "$ACCOUNT" \
    --state-file "$AWS_TEST_REPO/.state/$RUN_PREFIX-remote-gateway.json") || return 1
  printf '%s\n%s\n' "$test_all_info" "$test_remote_info"
  if test_all_ip=$(printf '%s' "$test_all_info" | jq -er 'select(.State == "running") | .PublicIpAddress // empty') &&
      test_remote_ip=$(printf '%s' "$test_remote_info" | jq -er 'select(.State == "running") | .PublicIpAddress // empty'); then
    ALL_IN_ONE_HOST="ec2-user@$test_all_ip"
    REMOTE_HOST="ec2-user@$test_remote_ip"
  else
    _aws_test_error 'Both VMs must be running with public IPs; wait and rerun verify.'
    return 1
  fi
  printf 'All-in-one login: %s\nRemote gateway login: %s\nSSH key: %s\n' \
    "$ALL_IN_ONE_HOST" "$REMOTE_HOST" "${SSH_KEY:-not set}"
}

aws_test_ssh() {
  local test_host
  case "${1:-}" in
    all-in-one) test_host=${ALL_IN_ONE_HOST:-} ;;
    remote-gateway) test_host=${REMOTE_HOST:-} ;;
    *) _aws_test_error 'Select all-in-one or remote-gateway.'; return 1 ;;
  esac
  if [ -z "$test_host" ] || [ ! -f "${SSH_KEY:-}" ]; then
    _aws_test_error 'Run verify successfully and set SSH_KEY to the matching private test key.'
    return 1
  fi
  ssh -o IdentitiesOnly=yes -i "$SSH_KEY" "$test_host"
}
