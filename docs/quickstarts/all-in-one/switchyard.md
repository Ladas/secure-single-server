# Switchyard deployment quickstart

Choose this profile to route OpenAI Chat Completions between
administrator-selected Weak and Strong models. It runs as the same persistent
Praxis service but adds a loopback listener on port `8082`.

This profile keeps all limiter and Switchyard state in memory. It cannot be
combined with the Valkey profile in the current deployment.

Configuration template:
[`shared-gateway-switchyard.yaml.in`](../../../configs/all-in-one/shared-gateway-switchyard.yaml.in).

The administrator runs the deployment scripts. Ordinary users do not receive
the scripts, configuration, or repository. The scripts validate the host,
create the locked service account, install root-owned configuration and
Quadlets, render the administrator-selected models, and start and verify the
systemd user service.

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

## 3. Create provider and judge secrets

Enter your secrets: paste this block and enter each API key at its prompt.
Input is hidden. If these versioned secrets already exist, skip this step
and reuse their names.

```console
{
  read -r -s -p 'OpenAI API key: ' PRAXIS_OPENAI_KEY; printf '\n'
  read -r -s -p 'Anthropic API key: ' PRAXIS_ANTHROPIC_KEY; printf '\n'
  read -r -s -p 'Switchyard judge API key: ' PRAXIS_JUDGE_KEY; printf '\n'
}
```

Copy and run unchanged in the same RHEL shell to store the secrets:

```console
printf '%s' "$PRAXIS_OPENAI_KEY" \
  | sudo scripts/common/secret-set openai v1
printf '%s' "$PRAXIS_ANTHROPIC_KEY" \
  | sudo scripts/common/secret-set anthropic v1
unset PRAXIS_OPENAI_KEY PRAXIS_ANTHROPIC_KEY
printf '%s' "$PRAXIS_JUDGE_KEY" \
  | sudo scripts/common/secret-set judge v1
unset PRAXIS_JUDGE_KEY
```

## 4. Select accepted models

Choose three model IDs supported by the configured OpenAI endpoint:

- `JUDGE_MODEL` classifies each admitted request;
- `WEAK_MODEL` handles simpler requests; and
- `STRONG_MODEL` handles harder requests.

The administrator fixes these values in protected configuration. Callers
cannot override the selected Weak or Strong target.

Enter your settings: paste this block and supply the three model IDs when
prompted. These are model names, not API keys.

```console
{
  read -r -p 'Judge model ID: ' JUDGE_MODEL
  read -r -p 'Weak model ID: ' WEAK_MODEL
  read -r -p 'Strong model ID: ' STRONG_MODEL
}
```

## 5. Install and verify Switchyard

Copy and run unchanged in the same RHEL shell:

```console
sudo scripts/all-in-one/install \
  --profile switchyard \
  --openai-secret praxis-openai-api-key-v1 \
  --anthropic-secret praxis-anthropic-api-key-v1 \
  --judge-secret praxis-judge-api-key-v1 \
  --judge-model "$JUDGE_MODEL" \
  --weak-model "$WEAK_MODEL" \
  --strong-model "$STRONG_MODEL"
sudo scripts/common/status
sudo scripts/common/verify --host
```

Expected listeners are:

| Address | API |
| --- | --- |
| `127.0.0.1:8080` | Direct OpenAI Responses and Chat Completions |
| `127.0.0.1:8081` | Direct native Anthropic Messages |
| `127.0.0.1:8082` | Switchyard OpenAI Chat Completions only |

Token admission occurs before the judge. Weak and Strong settle against the
same catch-all token allowance. The judge's tokens are outside that allowance.
Judge failure is closed, and failure of the selected target does not try the
other target.

For the direct endpoints, use the [user workflow](users.md).
Point a Chat Completions client at `http://127.0.0.1:8082/v1` to use
Switchyard. Responses clients such as Codex remain on port `8080`.

## Change from another profile

Profiles are mutually exclusive. Remove the current profile before installing
Switchyard:

```console
sudo scripts/common/uninstall
```
