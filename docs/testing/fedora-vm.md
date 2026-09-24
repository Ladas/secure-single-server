# Full Fedora VM: installer development

Use a normal **Fedora Server/Workstation VM**, not Fedora CoreOS. This checks
installer behavior quickly but does not qualify RHEL packages or support.
Use two disposable VMs, or uninstall/snapshot-reset between scenarios.

## Create or reuse a VM

An existing mutable Fedora VM with sudo, systemd and SELinux is suitable.
On a Mac M4, use native `aarch64`; on Intel/AMD, use native `x86_64`.
The [Fedora Server download](https://fedoraproject.org/server/download/)
provides both. With [UTM on macOS](https://docs.getutm.app/installation/macos/),
choose **Virtualize → Linux**, select the native ISO and install a minimal
server with an administrator account. Suggested test allocation: 4 vCPUs,
8 GiB RAM and 50 GiB disk. These hosted-model tests need no GPU.

Use a private/shared VM network reachable from your Mac. In the guest console:

```console
sudo systemctl enable --now sshd
ip -brief address
getenforce
test -f /sys/fs/cgroup/cgroup.controllers
sudo dnf install -y podman python3 openssl policycoreutils-python-utils jq curl git tmux
```

Keep SELinux enforcing. Authorize your dedicated SSH public key through the
VM console or existing administrator login; do not disable SSH host-key checks.
If your VM uses port forwarding, set an SSH host alias with its port/key and
use that alias in the quickstart's login prompt.

## Choose the scenario

| Scenario | Instructions | Fedora difference |
| --- | --- | --- |
| All-in-one | [Memory](../quickstarts/all-in-one/in-memory.md), then [Valkey](../quickstarts/all-in-one/valkey.md) | Add `--development-fedora` to every `install` or `upgrade` invocation |
| Remote gateway | [Private-CA preparation and security tests](remote-gateway.md), then [install](../quickstarts/remote-gateway/install.md) | Add `--development-fedora` to every `install` or `upgrade` invocation |

For example, preparing either scenario is explicit:

```console
sudo scripts/all-in-one/install --prepare --development-fedora
```

On the remote VM instead:

```console
sudo scripts/remote-gateway/install --prepare --development-fedora
```

Transfer the reviewed bundle as described in the chosen quickstart. Cloning
the PR branch inside a disposable development VM is also valid, but not
required. Do not clone `main` and assume it contains an unmerged change.

## Acceptance loop

1. Use dummy provider secrets first; test service startup, file ownership,
   host verification and reboot. Dummy secrets cannot complete inference tests.
2. All-in-one: create two ordinary users; confirm loopback access and denied
   access to service files/control. Remote: use two distinct caller JWTs from
   the Mac; confirm private ports and TLS/JWT denials.
3. Add real test provider keys using hidden prompts in the quickstart, then
   run [harness acceptance](harnesses.md) for memory and Valkey.
4. Repeat on [RHEL 9](rhel-vm.md), then [AWS RHEL](aws.md). Record Fedora and
   RHEL results separately; do not label Fedora results as RHEL acceptance.

An SSH disconnect must not stop the gateway. Reboot the disposable guest,
reconnect and run `sudo scripts/common/verify --host` from the deployment
bundle. Test retained Valkey quota state separately from container readiness.
