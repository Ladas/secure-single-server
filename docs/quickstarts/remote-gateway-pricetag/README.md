# Remote gateway with PriceTag

Run Praxis, MaaS, PriceTag and PostgreSQL on one RHEL host. Connect local
OpenCode with a user key and a monthly USD budget.

**Needs:** a fresh RHEL 9.6 x86_64 host with sudo, outbound HTTPS, and inbound
SSH/8443 from your IP; Git, Python 3 and OpenCode on your workstation.
The tested VM has 8 vCPUs, 32 GiB RAM and 150 GiB disk. No GPU is needed.

## 1. Set the connection

Run from your checked-out `secure-single-server` repository on your workstation:

```console
RHEL_HOST=ec2-user@YOUR_SERVER_IP
SSH_KEY="$HOME/.ssh/YOUR_KEY"
GATEWAY_HOST="${RHEL_HOST#*@}"
REPO="$PWD"
```

<details>
<summary>Need a test VM? Create one with the AWS helper</summary>

Follow the [AWS test-VM example](../../testing/aws-pricetag.md), then continue
below in the same shell. It sets `RHEL_HOST` and `SSH_KEY` for you; the final
block derives `GATEWAY_HOST` and `REPO`. Skip the connection block above.

</details>

## 2. Copy and install

Copy the checked-out **commit**, then install over SSH:

```console
SSH_OPTS=(-o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY")
(
  set -o pipefail
  git -C "$REPO" archive HEAD | ssh "${SSH_OPTS[@]}" "$RHEL_HOST" \
    'mkdir -p ~/secure-single-server && tar -xf - -C ~/secure-single-server'
) &&
ssh -t "${SSH_OPTS[@]}" "$RHEL_HOST" \
  "cd ~/secure-single-server && sudo scripts/pricetag/install --mode real --hostname '$GATEWAY_HOST' --provider openai --provider pricetag --monthly-usd 5 --yes"
```

Enter the **OpenAI key**, then the **hosted PriceTag URL and key** when prompted.
Keys are hidden and stored as Podman secrets. Remove either `--provider` option
if you use only one provider. For a DNS certificate, set `GATEWAY_HOST` to that
DNS name before installation.

The installer builds pinned MaaS/PriceTag images, pulls Praxis and starts the
services. It creates `admin`, `alice` and `bob`; Alice and Bob each get $5/month.
It refuses existing deployments. [Manual installation](manual.md) ·
[Credential-file automation and provider options](providers.md)

## 3. Open the dashboards

Print the browser URL and the saved keys over SSH:

```console
printf 'https://%s:8443/login\n' "$GATEWAY_HOST"
ssh "${SSH_OPTS[@]}" "$RHEL_HOST" \
  'for user in admin alice bob; do printf "\n%s: " "$user"; sudo cat "/root/pricetag-admin/$user.key"; printf "\n"; done'
```

Open that URL, trust the deployment certificate and paste the admin key.
For the personal dashboard, use `alice.key` instead, in a separate browser
profile. Treat printed keys as passwords; do not share the terminal output.
[Create users, set budgets and rotate keys](users.md)

## 4. Connect local OpenCode

Copy the CA and Alice's key into a private local directory:

```console
CLIENT_DIR="$HOME/.config/praxis-pricetag/$GATEWAY_HOST"
umask 077
mkdir -p "$CLIENT_DIR"
chmod 700 "$CLIENT_DIR"
ssh "${SSH_OPTS[@]}" "$RHEL_HOST" 'sudo cat /etc/praxis-pricetag/ca.pem' > "$CLIENT_DIR/ca.pem"
ssh "${SSH_OPTS[@]}" "$RHEL_HOST" 'sudo cat /root/pricetag-admin/alice.key' > "$CLIENT_DIR/alice.key"
chmod 600 "$CLIENT_DIR/ca.pem" "$CLIENT_DIR/alice.key"
GATEWAY_URL="https://$GATEWAY_HOST:8443"
curl --fail --cacert "$CLIENT_DIR/ca.pem" "$GATEWAY_URL/v1/models" | \
  python3 -c 'import json,sys; print("\n".join(m["id"] for m in json.load(sys.stdin)["data"]))'
```

Pick an alias from that list and launch from your project:

```console
MODEL='COPY_AN_ALIAS_FROM_THE_LIST'
cd /path/to/your/project
python3 "$REPO/scripts/pricetag/harness" opencode \
  --url "$GATEWAY_URL" --key-file "$CLIENT_DIR/alice.key" \
  --ca-file "$CLIENT_DIR/ca.pem" --model "$MODEL"
```

All enabled models are available in OpenCode's model picker for this session.
Its persistent configuration is unchanged.

<details>
<summary>What the helper does — and native OpenCode configuration without it</summary>

The helper reads `/v1/models`, groups aliases by OpenAI or Anthropic API, and
copies their context/output limits. It supplies the key and CA for this process
and launches OpenCode using `OPENCODE_CONFIG_CONTENT`. It does not install
OpenCode, issue keys or modify saved OpenCode settings.

To use native configuration instead, run this on your workstation after the CA
and key copy above. It needs `jq` and writes a separate configuration file with
all advertised models; the key stays in `alice.key` and is referenced by path.

```console
curl --fail --cacert "$CLIENT_DIR/ca.pem" "$GATEWAY_URL/v1/models" \
  -o "$CLIENT_DIR/models.json"
jq --arg base "$GATEWAY_URL/v1" --arg key "{file:$CLIENT_DIR/alice.key}" \
  --arg model "$MODEL" '
  {provider: (reduce .data[] as $m ({};
    reduce $m.praxis.apis[] as $api (. ;
      if ($api == "openai" or $api == "anthropic") then
        ("praxis-" + $api) as $id |
        .[$id] //= {name: $id,
          npm: (if $api == "anthropic" then "@ai-sdk/anthropic" else "@ai-sdk/openai-compatible" end),
          options: {baseURL: $base, apiKey: $key}, models: {}} |
        .[$id].models[$m.id] = {name: $m.id,
          limit: {context: $m.praxis.context, output: $m.praxis.output}}
      else . end))), disabled_providers: []} |
  .enabled_providers = (.provider | keys) |
  .model = ((first(["praxis-openai", "praxis-anthropic"][] as $id | select(.provider[$id].models[$model]) | $id)
    // error("Selected model is missing")) + "/" + $model)
' "$CLIENT_DIR/models.json" > "$CLIENT_DIR/opencode.json"
NODE_EXTRA_CA_CERTS="$CLIENT_DIR/ca.pem" \
  OPENCODE_CONFIG_CONTENT="$(cat "$CLIENT_DIR/opencode.json")" opencode
```

This file is only loaded for that invocation. Rerun the catalog/configuration
commands when the server's models change. OpenCode still merges unrelated
settings from your existing configuration. For a hand-maintained catalog, edit
this file's `provider` entries and model limits rather than regenerating it.
See [OpenCode configuration](https://opencode.ai/docs/config/) and
[custom providers](https://opencode.ai/docs/providers/#custom-provider).

</details>

## Operations

[Providers](providers.md) · [Users, keys and budgets](users.md) ·
[Manual installation](manual.md) · [Mock benchmarks](../../testing/pricetag-perf.md)

**Pilot limits:** keep this host restricted to trusted administrators. MaaS
management stays private. Keys expire within 90 days; revoking a key does not
end an existing dashboard session. Retention, upgrades and recovery still need
qualification. [Details](users.md#limits)
