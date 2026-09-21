# Test in a local RHEL 9 VM

Use this path to exercise the complete installer, rootless Podman, SELinux,
systemd user services, logout, and reboot behavior before testing in AWS.

## Create the VM

On macOS, install Red Hat build of Podman Desktop, then install its Red Hat
Authentication and RHEL VMs extensions. Sign in, open **Settings → RHEL VMs**,
and create a RHEL 9 VM with approximately 4 CPUs, 8 GiB memory, and 40 GiB
disk. Open its details page to obtain the configured SSH destination.

Use the native guest architecture:

| Mac | RHEL VM | Notes |
| --- | --- | --- |
| Apple Silicon, including M4 | `aarch64` | Preferred; do not emulate `x86_64` for normal testing |
| Intel | `x86_64` | Native architecture |

Both architectures are targets, not yet qualified RHEL deployments. The
commands are the same, and the installer checks the selected images against
the guest architecture. Complete and record the checks on each architecture
separately. GPU drivers and local vLLM require separate hardware tests.

## Put the repository in the VM

A clone inside this non-production VM preserves the tested Git revision.
Production quickstarts instead transfer only an administrator deployment
bundle. On your Mac, start Bash:

```console
bash
```

Enter the VM administrator login and an optional absolute SSH private-key
path (no surrounding quotes; blank uses your SSH defaults):

```console
{
  read -r -p 'RHEL VM administrator login: ' RHEL_VM
  read -r -p 'SSH private-key path (Enter for SSH defaults): ' SSH_KEY
}
```

Copy and run unchanged:

```console
SSH_OPTIONS=()
if [[ -n "$SSH_KEY" ]]; then
  SSH_OPTIONS=(-i "$SSH_KEY" -o IdentitiesOnly=yes)
fi
ssh -t "${SSH_OPTIONS[@]}" "$RHEL_VM" 'bash -l'
```

Inside the VM, enter the repository URL and branch containing the change.
For an open PR, use its head fork/branch; `main` may not contain it yet:

```console
{
  read -r -p 'Repository HTTPS URL: ' REPOSITORY_URL
  read -r -p 'Branch to test: ' BRANCH
}
```

Copy and run unchanged. The last command records the revision for test
evidence; it does not configure the deployment:

```console
sudo dnf install -y git
git clone --branch "$BRANCH" "$REPOSITORY_URL" ~/secure-single-server
cd ~/secure-single-server
git rev-parse HEAD
```

For unpushed changes, use the bundle-transfer step of the [in-memory
quickstart](../quickstarts/in-memory.md) instead, and record the local revision
plus the uncommitted diff. In that case use `~/secure-single-server-deploy`
as the working directory below.

## Install and verify

Inside the RHEL VM:

```console
sudo dnf install -y git podman openssl policycoreutils-python-utils tmux curl jq tar gzip python3
sudo scripts/shared-gateway/install --prepare
printf '%s' local-openai-test \
  | sudo scripts/shared-gateway/secret-set openai vm1
printf '%s' local-anthropic-test \
  | sudo scripts/shared-gateway/secret-set anthropic vm1
sudo scripts/shared-gateway/install \
  --profile memory \
  --openai-secret praxis-openai-api-key-vm1 \
  --anthropic-secret praxis-anthropic-api-key-vm1
sudo scripts/shared-gateway/status
sudo scripts/shared-gateway/verify --host
```

Dummy credentials are enough for lifecycle checks. Use real versioned
secrets only when testing provider protocols, streaming, tools, accounting,
and coding harnesses.

## Test reboot and user separation

```console
sudo reboot
```

Reconnect from the same Mac shell when the VM returns:

```console
ssh -t "${SSH_OPTIONS[@]}" "$RHEL_VM" 'bash -l'
```

Inside the VM (use `~/secure-single-server-deploy` for a transferred bundle):

```console
cd ~/secure-single-server
sudo scripts/shared-gateway/status
sudo scripts/shared-gateway/verify --host
```

Create two ordinary VM accounts and test the [user
workflow](../user-workflow.md) from each. Both accounts should reach the
loopback inference ports. Neither should be able to read `/etc/praxis`, enter
`/var/lib/praxis-svc`, inspect the service account Podman store, or control
its systemd user services.

Restore a clean VM snapshot before separately testing the Valkey and
Switchyard profiles. Local VM success is the pre-AWS gate; it does not replace
final acceptance on the target AWS RHEL instance.

Next, run [in-memory and Valkey harness acceptance](harnesses.md) with real
provider keys stored by the administrator. Switchyard provider testing is a
later phase. Do not capture snapshots containing real keys for distribution.
