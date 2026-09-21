# Test with the Fedora CoreOS Podman machine

Use the Podman machine for fast image and configuration checks from macOS.
It is not a RHEL deployment test.

## Start the machine

```console
podman machine list
podman machine start
podman info
```

The VM uses the Mac architecture: `aarch64` on Apple Silicon and `x86_64` on
an Intel Mac.

## Run the checks

Run these commands in the repository checkout on the Mac. Podman sends the
container work to its Fedora CoreOS VM; do not clone the repository into that
VM. Start at the root of the checkout/worktree you are reviewing (not a second
copy on `main`). See [static-check prerequisites](README.md#fast-local-checks).

```console
tests/shared-gateway-static.sh
CONTAINER_ENGINE=podman tests/shared-gateway-image.sh
CONTAINER_ENGINE=podman tests/shared-gateway-valkey-image.sh
```

The checks validate the image architecture, rendered Praxis configurations,
non-root execution, Valkey ACL restrictions, and Valkey AOF restart behavior.
They use dummy credentials and make no paid provider calls. On an M4 this
is native arm64 validation; amd64 is covered by a separate native CI runner
and, later, the AWS RHEL host. Do not use emulation as proof of native support.

To make manual provider calls, continue with the [disposable Podman
test](podman.md).

## Boundary

Do not run the persistent installer in the Podman machine. Fedora CoreOS does
not qualify the RHEL package, SELinux, systemd user-service, logout, or reboot
path. Run those checks in a [local RHEL VM](rhel-vm.md).
Then follow [harness acceptance](harnesses.md) to test protected real provider
keys with the in-memory and Valkey service profiles.
