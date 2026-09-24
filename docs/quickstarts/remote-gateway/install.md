# Install the remote gateway

Run workstation commands from a reviewed checkout. The server needs RHEL 9,
native amd64/arm64, sudo access, SELinux enforcing and cgroups v2. No Git
checkout is needed on RHEL. Do not deploy both scenarios on the same host.
The workstation needs Python 3.9+, OpenSSL and SSH/SCP. Keep issuer and TLS
private keys in administrator-only storage, outside the checkout.

## 1. Prepare administrator material

Use Bash on the workstation:

```console
bash
```

Enter the SSH login/key and existing TLS certificate/key paths. The TLS
certificate must cover the hostname/IP in the users' URL and remain valid for
at least seven days. Use a public or
organization CA for deployment; [private-CA VM testing](../../testing/remote-gateway.md)
is available for disposable tests. Never disable certificate verification.

```console
{
  read -r -p 'RHEL administrator login (user@host): ' RHEL_HOST
  read -r -p 'SSH private-key path (Enter for SSH defaults): ' SSH_KEY
  read -r -p 'TLS PEM certificate/full-chain absolute path: ' TLS_CERT
  read -r -p 'TLS private-key absolute path: ' TLS_KEY
  read -r -p 'New private JWT issuer directory absolute path: ' ISSUER_DIR
}
```

Copy unchanged. The issuer directory must not exist. Store it securely;
losing its private key prevents issuing new tokens for this verification key.

```console
scripts/remote-gateway/credentials check-tls --cert "$TLS_CERT" --key "$TLS_KEY"
scripts/remote-gateway/credentials init-jwt --directory "$ISSUER_DIR"
SSH_OPTIONS=()
if [[ -n "$SSH_KEY" ]]; then
  SSH_OPTIONS=(-i "$SSH_KEY" -o IdentitiesOnly=yes)
fi
ssh "${SSH_OPTIONS[@]}" "$RHEL_HOST" \
  'install -d -m 0700 ~/secure-single-server-deploy/{configs,scripts,tests,material}'
scp "${SSH_OPTIONS[@]}" -pr configs/all-in-one configs/remote-gateway configs/common \
  "$RHEL_HOST:~/secure-single-server-deploy/configs/"
scp "${SSH_OPTIONS[@]}" -pr scripts/common scripts/remote-gateway \
  "$RHEL_HOST:~/secure-single-server-deploy/scripts/"
scp "${SSH_OPTIONS[@]}" -p tests/shared-gateway-host.sh \
  "$RHEL_HOST:~/secure-single-server-deploy/tests/"
scp "${SSH_OPTIONS[@]}" "$TLS_CERT" "$RHEL_HOST:~/secure-single-server-deploy/material/tls.pem"
scp "${SSH_OPTIONS[@]}" "$TLS_KEY" "$RHEL_HOST:~/secure-single-server-deploy/material/tls-key.pem"
scp "${SSH_OPTIONS[@]}" "$ISSUER_DIR/public.pem" "$RHEL_HOST:~/secure-single-server-deploy/material/jwt-public.pem"
ssh -t "${SSH_OPTIONS[@]}" "$RHEL_HOST" 'bash -l'
```

Only the public JWT key is copied. The TLS key is a separate runtime secret.

## 2. Prepare RHEL and provider secrets

The remaining commands in this section run on RHEL:

```console
cd ~/secure-single-server-deploy
chmod 600 material/tls-key.pem
sudo dnf install -y podman python3 openssl policycoreutils-python-utils jq curl
sudo scripts/remote-gateway/install --prepare
set +x
set +a
unset PRAXIS_OPENAI_KEY PRAXIS_ANTHROPIC_KEY
sudo -v
```

Enter dedicated provider credentials in a private, unrecorded administrator
terminal. No shell tracing or sudo input/session recording may capture them.

```console
{
  read -r -s -p 'OpenAI API key: ' PRAXIS_OPENAI_KEY; printf '\n'
  read -r -s -p 'Anthropic API key (Enter to skip Claude Code): ' PRAXIS_ANTHROPIC_KEY; printf '\n'
}
```

Store them under the service account; do not give them to harness users:

```console
printf '%s' "$PRAXIS_OPENAI_KEY" | sudo scripts/common/secret-set openai v1
printf '%s' "${PRAXIS_ANTHROPIC_KEY:-provider-not-configured}" \
  | sudo scripts/common/secret-set anthropic v1
unset PRAXIS_OPENAI_KEY PRAXIS_ANTHROPIC_KEY
sudo scripts/common/secret-set valkey v1 --generate
```

## 3. Install persistent token quotas

First restrict network ingress: SSH only from the administrator's IP and TCP
8443 only from approved clients. The installer does **not** change firewall
rules. [VM testing](../../testing/remote-gateway.md) gives an explicit firewalld
example; AWS also needs the corresponding security-group rule.

```console
sudo scripts/remote-gateway/install \
  --profile valkey \
  --openai-secret praxis-openai-api-key-v1 \
  --anthropic-secret praxis-anthropic-api-key-v1 \
  --valkey-image docker.io/valkey/valkey@sha256:63346cb24a61221e76bdf41acce99b3968a9fa83d8122144deab45394b27b4f2 \
  --valkey-url-secret praxis-valkey-url-v1 \
  --valkey-acl-secret praxis-valkey-acl-v1 \
  --tls-cert "$PWD/material/tls.pem" \
  --tls-key "$PWD/material/tls-key.pem" \
  --jwt-public-key "$PWD/material/jwt-public.pem"
sudo scripts/common/status
sudo scripts/common/verify --host
```

Expected: only `0.0.0.0:8443` is published by Praxis. Admin/Valkey ports remain
inside the private container network. Confirm TLS trust and unauthenticated
denial from the client machine before distributing tokens.

For development-only memory installation, use the command above with
`--profile memory` and omit all three `--valkey-*` options. To change profiles,
run `sudo scripts/common/uninstall` first; it retains secrets and Valkey data.

## 4. Issue each user's caller credential

Back on the administrator workstation, in the shell holding `ISSUER_DIR`:

```console
{
  read -r -p 'Stable user/application ID: ' CALLER
  read -r -p 'New JWT output file absolute path: ' TOKEN_FILE
}
scripts/remote-gateway/credentials issue \
  --key "$ISSUER_DIR/private.pem" --subject "$CALLER" \
  --days 30 --output "$TOKEN_FILE"
```

Deliver only that caller's JWT through an approved secret-sharing channel.
Supply the HTTPS URL, accepted model IDs and, for a private CA, its public
certificate. Continue with [user setup](users.md).

## Operations

Use `sudo scripts/common/status` and `verify --host`. For a reviewed image,
certificate or key update, rerun the complete install command with `--replace`.
Do not modify `/etc/praxis` files directly: the manifest rejects drift.
Keep the staging directory private because it contains the server TLS key.

Renew JWTs before expiry. To revoke all existing JWTs, create a new issuer
keypair, replace the deployed public key and restart through the installer,
then issue replacement JWTs. Individual immediate revocation is not available.
Rotate compromised provider credentials separately using new secret versions.
