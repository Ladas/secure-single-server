# Development and non-production testing

Use these instructions to validate a change before touching a shared RHEL
server. They are repository developer instructions, not deployment
quickstarts.

## Choose the smallest useful environment

| Environment | What it proves | What it does not prove |
| --- | --- | --- |
| macOS static checks | Scripts parse, configuration renders, links resolve, and unsafe listener patterns are absent | Container startup or RHEL integration |
| Fedora CoreOS Podman machine | Pinned images start on the Mac's native architecture; Praxis profiles and Valkey persistence work in containers | RHEL packages, SELinux labels, user systemd, logout, or reboot |
| Disposable Podman container | A developer can inspect configuration and make provider calls without installing a service | Locked service account, boot startup, recovery, or protected administrator ownership |
| Local RHEL 9 VM | Complete installer, rootless Podman, SELinux, user systemd, account separation, logout, and reboot | Final AWS networking, IAM, or target-instance behavior |

## Fast local checks

Static checks require Bash, Git, `jq`, `rg` (ripgrep), and Ruby with Psych.
Install ShellCheck too; the script warns and skips linting if it is missing.

From the repository root on macOS with the Podman machine running:

```console
tests/shared-gateway-static.sh
CONTAINER_ENGINE=podman tests/shared-gateway-image.sh
CONTAINER_ENGINE=podman tests/shared-gateway-valkey-image.sh
```

Continue with one of these instructions:

- [Fedora CoreOS Podman machine](fedora-coreos.md) for the normal Mac image
  and configuration loop;
- [disposable Podman container](podman.md) for manual provider calls; or
- [local RHEL 9 VM](rhel-vm.md) for the full pre-production host gate.

Do not use the Fedora CoreOS or disposable-container path as evidence that the
persistent RHEL deployment is accepted. The RHEL VM is the minimum complete
host-integration test; the target RHEL environment remains the final gate.

## Architecture qualification

Both pinned image indexes include `linux/amd64` and `linux/arm64`. The
installer maps host `x86_64` to `amd64` and `aarch64` to `arm64`. Container
tests compare the image with the engine server, including a remote Podman VM;
an emulated image does not count as native qualification.

The [CI workflow](../../.github/workflows/validate.yml) runs static checks,
Praxis startup, and Valkey ACL/persistence tests on native amd64 and arm64
Linux runners, using dummy credentials only. CI does not run the RHEL installer
or make paid provider calls. Check the PR's actual job results after pushing.

| Gate | arm64 | amd64 |
| --- | --- | --- |
| Image available in both pinned indexes | Present | Present |
| Native image tests | Mac M4 Podman; CI job | Native CI job |
| RHEL 9 installer, SELinux, account isolation, logout, reboot | Pending: local RHEL VM | Pending: AWS RHEL VM |
| In-memory and Valkey, all three harnesses with real providers | Pending | Pending |

After the no-key checks, follow [harness acceptance](harnesses.md) on the local
RHEL VM, then repeat on AWS RHEL. This round covers **in-memory and Valkey**;
real-provider Switchyard acceptance is a separate next phase. A successful
arm64 run does not complete the amd64 column.
