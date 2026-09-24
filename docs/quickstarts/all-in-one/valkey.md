# Valkey deployment quickstart

Choose this profile when consumed token allowance must survive a Praxis
restart. It runs Praxis and one private Valkey container under the locked
`praxis-svc` account. Valkey is a standalone Redis-compatible server; no
separate Redis service is required.

Valkey stores only token-quota state. Request-rate buckets remain in Praxis
memory and reset with Praxis. This profile does not include Switchyard.

Configuration:
[`shared-gateway-valkey.yaml`](../../../configs/all-in-one/shared-gateway-valkey.yaml).

The administrator runs the deployment scripts. Ordinary users do not receive
the scripts, configuration, or repository. The scripts validate the host,
create the locked service account, install root-owned configuration and
Quadlets, and start and verify the systemd user services.

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

## 2. Prepare the host

Copy and run unchanged:

```console
sudo dnf install -y podman openssl policycoreutils-python-utils jq tar gzip
sudo scripts/all-in-one/install --prepare
```

## 3. Create provider secrets

OpenAI is used by Codex and OpenCode; Claude Code also requires an Anthropic
key. Use dedicated test credentials on a test host. Keep keys out of command
history, files, chat, and harness accounts. Use a private, unrecorded
administrator terminal; `sudo` I/O recording must not capture secret input.
Podman secrets are not an encrypted vault: root and the service account
remain trusted.

If both provider secrets already exist, reuse their names and go to step 4.
Otherwise refresh sudo authentication and disable tracing/automatic export:

```console
set +x
set +a
unset PRAXIS_OPENAI_KEY PRAXIS_ANTHROPIC_KEY
sudo -v
```

Enter your secrets: paste this block and enter each API key at its prompt.
Input is hidden.

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

Skipping Anthropic stores a non-secret dummy value; Claude Code cannot pass
acceptance until an administrator installs a real Anthropic key.

## 4. Create the Valkey secrets

```console
sudo scripts/common/secret-set valkey v1 --generate
```

This creates an ACL secret and a connection-URL secret with a generated
password. The password is not printed.

## 5. Install and verify the Valkey profile

```console
sudo scripts/all-in-one/install \
  --profile valkey \
  --openai-secret praxis-openai-api-key-v1 \
  --anthropic-secret praxis-anthropic-api-key-v1 \
  --valkey-image docker.io/valkey/valkey@sha256:63346cb24a61221e76bdf41acce99b3968a9fa83d8122144deab45394b27b4f2 \
  --valkey-url-secret praxis-valkey-url-v1 \
  --valkey-acl-secret praxis-valkey-acl-v1
sudo scripts/common/status
sudo scripts/common/verify --host
```

Praxis publishes only `127.0.0.1:8080` and `127.0.0.1:8081`. Valkey port
`6379` and Praxis admin port `9901` are not published. Token-quota data is kept
in the `praxis-valkey-data` volume with AOF persistence.

Continue with the [user workflow](users.md).

## Change from another profile

Profiles are mutually exclusive. Remove the installed profile first; the
default removal preserves provider secrets and Valkey data:

```console
sudo scripts/common/uninstall
```

Then run the Valkey install command above. To permanently remove its stored
token-quota data during removal, use:

```console
sudo scripts/common/uninstall --purge-valkey-data
```

Purging the volume cannot be undone.
