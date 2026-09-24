#!/usr/bin/env bash

set -euo pipefail

TEST_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "${TEST_DIR}/.." && pwd)"
# shellcheck source=scripts/common/lib.sh
source "${REPO_DIR}/scripts/common/lib.sh"

expect_failure() {
  if ( "$@" ) >/dev/null 2>&1; then
    printf 'error: expected rejection from %s\n' "$1" >&2
    exit 1
  fi
}

[[ "$(oci_architecture x86_64)" == amd64 ]] || die "x86_64 mapping failed"
[[ "$(oci_architecture amd64)" == amd64 ]] || die "amd64 mapping failed"
[[ "$(oci_architecture aarch64)" == arm64 ]] || die "aarch64 mapping failed"
[[ "$(oci_architecture arm64)" == arm64 ]] || die "arm64 mapping failed"
expect_failure oci_architecture ppc64le
expect_failure oci_architecture ''
require_linux_image_platform praxis linux amd64 amd64
require_linux_image_platform valkey linux arm64 arm64
expect_failure require_linux_image_platform praxis linux arm64 amd64
expect_failure require_linux_image_platform valkey linux amd64 arm64
expect_failure require_linux_image_platform praxis windows amd64 amd64

# The engine server can differ from the laptop. Test its architecture, not
# the shell's uname, and reject emulation as evidence of native support.
# These mocks are invoked indirectly through check_native_image's engine argument.
# ShellCheck 0.9 reports SC2317; newer versions report SC2329.
# shellcheck disable=SC2317,SC2329
podman() {
  case "$*" in
    'info --format {{.Host.OS}}/{{.Host.Arch}}') printf '%s\n' "${fake_server_platform}" ;;
    'image inspect test-image --format {{.Os}}/{{.Architecture}}') printf '%s\n' "${fake_image_platform}" ;;
    *) return 2 ;;
  esac
}
# shellcheck disable=SC2317,SC2329
docker() {
  case "$*" in
    'info --format {{.OSType}}/{{.Architecture}}') printf '%s\n' "${fake_server_platform}" ;;
    'image inspect test-image --format {{.Os}}/{{.Architecture}}') printf '%s\n' "${fake_image_platform}" ;;
    *) return 2 ;;
  esac
}
for engine in podman docker; do
  for server_arch in x86_64 amd64 aarch64 arm64; do
    fake_server_platform="linux/${server_arch}"
    fake_image_platform="linux/$(oci_architecture "${server_arch}")"
    check_native_image "${engine}" test-image
  done
  fake_server_platform=linux/arm64
  fake_image_platform=linux/amd64
  expect_failure check_native_image "${engine}" test-image
  fake_server_platform=linux/x86_64
  fake_image_platform=linux/arm64
  expect_failure check_native_image "${engine}" test-image
  fake_server_platform=darwin/arm64
  expect_failure check_native_image "${engine}" test-image
done
unset -f podman docker

password_hash=69d6dc9618d24d693cad07557702696090d0f575d9c0868384b8001fd1252358
acl="$(valkey_acl "${password_hash}")"
[[ "${acl}" == "$(sed "s/SHA256_PASSWORD/${password_hash}/" "${REPO_DIR}/configs/common/valkey/users.acl.example")" ]] ||
  die "generated Valkey ACL differs from the example"
[[ " ${acl} " == *' +ping '* ]] || die "Valkey ACL lacks PING"
[[ " ${acl} " != *' +@all '* ]] || die "Valkey ACL grants unrestricted commands"
expect_failure valkey_acl invalid-hash
# Assert that the installer/secret helper actually use the tested functions.
# shellcheck disable=SC2016
grep -Fq 'expected_arch="$(oci_architecture "$(uname -m)")"' "${REPO_DIR}/scripts/common/install"
# shellcheck disable=SC2016
grep -Fq 'acl="$(valkey_acl "${password_hash}")"' "${REPO_DIR}/scripts/common/secret-set"

printf 'architecture mapping, native-image checks, and Valkey ACL unit checks passed\n'
