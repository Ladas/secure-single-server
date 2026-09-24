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
| Full Fedora VM | Both installers with an explicit development override; systemd/SELinux behavior | RHEL package and host qualification |
| Two AWS RHEL VMs | All-in-one and remote HTTPS/JWT under separate networking and state | Other architectures or untested harness/model combinations |

## Fast local checks

Static checks require Bash, Git, `jq`, `rg` (ripgrep), and Ruby with Psych.
The credential, AWS and remote image tests also need Python 3.9+ and OpenSSL.
AWS session tests cover Bash and, when installed, zsh; CI installs both shells.
Install ShellCheck too (0.11.0 matches CI); the script prints its version and
warns if linting is skipped because it is missing. CI pins the official Linux
binaries by version and SHA-256 for both architectures.

From the repository root on macOS with the Podman machine running:

```console
tests/shared-gateway-static.sh
CONTAINER_ENGINE=podman tests/shared-gateway-image.sh
CONTAINER_ENGINE=podman tests/shared-gateway-valkey-image.sh
python3 tests/remote-gateway/credentials.py
python3 tests/remote-gateway/security.py
python3 tests/aws/plan.py
python3 tests/aws/session.py
CONTAINER_ENGINE=podman python3 tests/remote-gateway/image.py
CONTAINER_ENGINE=podman python3 tests/remote-gateway/image.py --valkey
```

Continue with one of these instructions:

- [Fedora CoreOS Podman machine](fedora-coreos.md) for the normal Mac image
  and configuration loop;
- [disposable Podman container](podman.md) for manual provider calls; or
- [local RHEL 9 VM](rhel-vm.md) for the full pre-production host gate.

For an existing local Fedora VM, follow [full Fedora development](fedora-vm.md).
Test **all-in-one and remote gateway** separately, each with memory and Valkey.
Then use the [AWS two-VM guide](aws.md). The cloud helper does nothing unless
invoked; `plan` and `verify` are read-only, while `apply` requires confirmation.

Do not use the Fedora CoreOS or disposable-container path as evidence that the
persistent RHEL deployment is accepted. The RHEL VM is the minimum complete
host-integration test; the target RHEL environment remains the final gate.

## Architecture qualification

Both pinned image indexes include `linux/amd64` and `linux/arm64`. The
installer maps host `x86_64` to `amd64` and `aarch64` to `arm64`. Container
tests compare the image with the engine server, including a remote Podman VM;
an emulated image does not count as native qualification.

The [CI workflow](../../.github/workflows/validate.yml) runs static checks,
Praxis startup, Valkey ACL/persistence and synthetic remote TLS/JWT/quota tests on native amd64 and arm64
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
