# In-memory deployment quickstart

Development only: use the [Valkey profile](valkey.md) when daily token quotas
must survive a service or server restart.

This profile runs Praxis as a rootless container owned by the locked
`praxis-svc` account. systemd starts it at boot and restarts it after failure.
Request and token-quota state is kept in Praxis memory and resets whenever
Praxis restarts.

Configuration:
[`shared-gateway.yaml`](../../../configs/all-in-one/shared-gateway.yaml).

The administrator runs the deployment scripts. Ordinary users do not receive
the scripts, configuration, or repository. The scripts validate the host,
create the locked service account, install root-owned configuration and
Quadlets, and start and verify the systemd user service.

## 1. Transfer the administrator deployment bundle

Start in the reviewed repository checkout on the administrator's workstation.
You need SSH access to an administrator account with `sudo` on RHEL. Its public
key must already be authorized on the server; the private key stays on your
workstation. Git is not required on RHEL.

Copy and run this first to use Bash, including on macOS:

```console
bash
```

Enter your settings: paste this block, then answer each prompt and press
Enter. Use `user@hostname`, `user@IP`, or an SSH alias. For the key, enter an
absolute path without surrounding quotes; leave it blank to use your SSH
configuration or agent. These values remain in this workstation shell.

```console
{
  read -r -p 'RHEL administrator login: ' RHEL_HOST
  read -r -p 'SSH private-key path (Enter for SSH defaults): ' SSH_KEY
}
```

Copy and run unchanged to transfer the configuration, administrator scripts,
and RHEL host check to a private staging directory:

```console
SSH_OPTIONS=()
if [[ -n "$SSH_KEY" ]]; then
  SSH_OPTIONS=(-i "$SSH_KEY" -o IdentitiesOnly=yes)
fi
ssh "${SSH_OPTIONS[@]}" "$RHEL_HOST" \
  'install -d -m 0700 ~/secure-single-server-deploy ~/secure-single-server-deploy/configs ~/secure-single-server-deploy/scripts ~/secure-single-server-deploy/tests'
scp "${SSH_OPTIONS[@]}" -pr configs/all-in-one configs/common \
  "$RHEL_HOST:~/secure-single-server-deploy/configs/"
scp "${SSH_OPTIONS[@]}" -pr scripts/common scripts/all-in-one \
  "$RHEL_HOST:~/secure-single-server-deploy/scripts/"
scp "${SSH_OPTIONS[@]}" -p tests/shared-gateway-host.sh \
  "$RHEL_HOST:~/secure-single-server-deploy/tests/"
```

SSH may ask you to confirm the server's host key or unlock your private key.
Once the copies succeed, open a Bash session on RHEL:

```console
ssh -t "${SSH_OPTIONS[@]}" "$RHEL_HOST" 'bash -l'
```

All remaining steps run in that RHEL session, starting with:

```console
cd ~/secure-single-server-deploy
```

## 2. Install host packages

```console
sudo dnf install -y podman openssl policycoreutils-python-utils jq tar gzip
```

## 3. Prepare the service account

```console
sudo scripts/all-in-one/install --prepare
```

The command validates RHEL 9, SELinux enforcing, cgroups v2, Podman 4.6 or
newer, and the host architecture. It creates or validates `praxis-svc`, its
subordinate IDs, private home, and systemd lingering.

## 4. Create provider secrets

Use dedicated test credentials on a test host. OpenAI is used by Codex and
OpenCode; Claude Code also requires an Anthropic key. Do not paste keys into
commands, files, chat, or harness accounts. Run this in a private, unrecorded
administrator terminal; `sudo` I/O recording must not capture secret input.

First refresh sudo authentication and disable shell tracing/automatic export:

```console
set +x
set +a
unset PRAXIS_OPENAI_KEY PRAXIS_ANTHROPIC_KEY
sudo -v
```

Enter your secrets: paste this block and enter each API key at its prompt.
Input is hidden; pressing Enter finishes each value. Keys are kept temporarily
in shell variables and passed to the helper over standard input.

```console
{
  read -r -s -p 'OpenAI API key: ' PRAXIS_OPENAI_KEY; printf '\n'
  read -r -s -p 'Anthropic API key (Enter to skip Claude Code): ' PRAXIS_ANTHROPIC_KEY; printf '\n'
}
```

Copy and run unchanged in the same RHEL shell to store the secrets:

```console
printf '%s' "$PRAXIS_OPENAI_KEY" \
  | sudo scripts/common/secret-set openai v1
printf '%s' "${PRAXIS_ANTHROPIC_KEY:-provider-not-configured}" \
  | sudo scripts/common/secret-set anthropic v1
unset PRAXIS_OPENAI_KEY PRAXIS_ANTHROPIC_KEY
```

These commands create the versioned Podman secrets
`praxis-openai-api-key-v1` and `praxis-anthropic-api-key-v1`.
Skipping Anthropic stores a non-secret dummy value; calls to that provider
will fail until an administrator installs a real key. Podman secrets are not
an encrypted vault: root and the service account remain trusted.

## 5. Install and verify Praxis

```console
sudo scripts/all-in-one/install \
  --profile memory \
  --openai-secret praxis-openai-api-key-v1 \
  --anthropic-secret praxis-anthropic-api-key-v1
sudo scripts/common/status
sudo scripts/common/verify --host
```

Expected listeners are:

| Address | API |
| --- | --- |
| `127.0.0.1:8080` | OpenAI Responses and Chat Completions |
| `127.0.0.1:8081` | Native Anthropic Messages |

Admin port `9901` remains inside the container. The provider secrets and
configuration are unavailable to ordinary server users.

Continue with the [user workflow](users.md).

## Operate the service

```console
sudo scripts/common/status
sudo scripts/common/verify --host
```

For a reviewed same-profile update, create new versioned secrets and pass the
complete profile arguments. Enter the replacement keys first (hidden input):

```console
set +x
set +a
unset PRAXIS_OPENAI_KEY PRAXIS_ANTHROPIC_KEY
sudo -v
```

```console
{
  read -r -s -p 'New OpenAI API key: ' PRAXIS_OPENAI_KEY; printf '\n'
  read -r -s -p 'New Anthropic API key (Enter to skip Claude Code): ' PRAXIS_ANTHROPIC_KEY; printf '\n'
}
```

Copy and run unchanged to create version `v2` secrets and apply the update:

```console
printf '%s' "$PRAXIS_OPENAI_KEY" \
  | sudo scripts/common/secret-set openai v2
printf '%s' "${PRAXIS_ANTHROPIC_KEY:-provider-not-configured}" \
  | sudo scripts/common/secret-set anthropic v2
unset PRAXIS_OPENAI_KEY PRAXIS_ANTHROPIC_KEY

sudo scripts/common/upgrade --profile memory \
  --openai-secret praxis-openai-api-key-v2 \
  --anthropic-secret praxis-anthropic-api-key-v2
```

To remove the installed profile:

```console
sudo scripts/common/uninstall
```

Removal preserves Podman secrets, the service account, and its lingering
setting.
