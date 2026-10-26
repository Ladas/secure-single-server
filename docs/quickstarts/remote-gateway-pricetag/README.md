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
SSH_OPTS=(-o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY")
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
  "cd ~/secure-single-server && sudo scripts/pricetag/install --hostname '$GATEWAY_HOST'"
```

Choose providers, enter their keys at hidden prompts, then confirm with `install`.

- **Providers:** OpenAI, an external OpenAI-compatible/Messages service, or both.
- **Users:** admin is required; Alice/Bob are optional. Choose **Admin only** to
  [create your own user](users.md#create-a-user) afterward.
- **Defaults:** real providers, published images, $5/month per ordinary user.

<details>
<summary>Installer options and logs</summary>

| Option | Purpose |
| --- | --- |
| `--no-sample-users` | Create admin only. |
| `--monthly-usd 10` | Set the default per-user monthly allowance. |
| `--image-mode source` | Build application images; see [image options](images.md). |
| `--mode mock` | Use synthetic providers for [benchmarks](../../testing/pricetag-perf.md). |

External setup accepts one or both APIs; one key must cover the selected APIs.
Credentials and reviewed model presets are checked before installation.
For a DNS certificate, set `GATEWAY_HOST` to that name before running the installer.
Existing deployments are refused.

The installer prints progress and a private log path under `/var/log/`, plus a
`sudo tail -f` command. On failure, inspect that log before retrying; do not share
it without reviewing its contents.

[Manual installation](manual.md) · [Unattended provider setup](providers.md)

</details>

## 3. Open the dashboards

In the installation shell, print the login URL and admin key:

```console
printf 'https://%s:8443/login\n' "$GATEWAY_HOST"
ssh "${SSH_OPTS[@]}" "$RHEL_HOST" \
  'sudo cat /root/pricetag-admin/admin.key'
```

Open the URL, accept the deployment certificate and paste the admin key.
Personal dashboards are pending upstream; use the admin dashboard for usage.

## 4. Prepare the local connection

In the **workstation installation shell**, choose your user on the first line.
This copies the CA/key and prints a launch command for any project shell:

```console
INFERENCE_USER=alice  # Change to a user you created; do not use admin.
cd "$REPO"
CLIENT_DIR="$HOME/.config/praxis-pricetag/$GATEWAY_HOST"
umask 077
mkdir -p "$CLIENT_DIR"
chmod 700 "$CLIENT_DIR"
ssh "${SSH_OPTS[@]}" "$RHEL_HOST" 'sudo cat /etc/praxis-pricetag/ca.pem' > "$CLIENT_DIR/ca.pem"
KEY_FILE="$CLIENT_DIR/$INFERENCE_USER.key"
ssh "${SSH_OPTS[@]}" "$RHEL_HOST" "sudo cat /root/pricetag-admin/$INFERENCE_USER.key" > "$KEY_FILE"
chmod 600 "$CLIENT_DIR/ca.pem" "$KEY_FILE"
GATEWAY_URL="https://$GATEWAY_HOST:8443"
curl --fail --silent --show-error --cacert "$CLIENT_DIR/ca.pem" "$GATEWAY_URL/v1/models" \
  -o "$CLIENT_DIR/models.json"
MODEL=$(python3 -c 'import json,sys; rows=json.load(open(sys.argv[1]))["data"]; assert rows, "Gateway has no models"; print(rows[0]["id"])' "$CLIENT_DIR/models.json")
printf 'Initial model: %s\n' "$MODEL"
printf '\nCopy into any workstation shell opened in your project directory:\n\n'
printf 'export REPO=%q\nexport CLIENT_DIR=%q\nexport GATEWAY_URL=%q\nexport MODEL=%q\nexport KEY_FILE=%q\n' \
  "$REPO" "$CLIENT_DIR" "$GATEWAY_URL" "$MODEL" "$KEY_FILE"
printf '%s\n' \
  'python3 "$REPO/scripts/pricetag/harness" opencode \' \
  '  --url "$GATEWAY_URL" --key-file "$KEY_FILE" \' \
  '  --ca-file "$CLIENT_DIR/ca.pem" --model "$MODEL"'
```

The first model is selected automatically; all models remain in the picker.
The printed command contains file paths, never key contents.

## 5. Run OpenCode

In a **project shell**, paste the printed block. Each launch refreshes the catalog;
existing OpenCode settings are unchanged. Sessions for one user share their budget.

<details>
<summary>Switch users</summary>

Copy the other user's key with step 4, then launch with its path:

```console
KEY_FILE="$CLIENT_DIR/carol.key"  # Or the absolute path to another private user key.
python3 "$REPO/scripts/pricetag/harness" opencode --url "$GATEWAY_URL" \
  --key-file "$KEY_FILE" --ca-file "$CLIENT_DIR/ca.pem" --model "$MODEL"
```

</details>

<details>
<summary>Save native configuration and a launcher — no exports needed on later runs</summary>

Run in the **workstation setup shell** after step 4. Requires `jq`.
Choose a user key below. This saves all advertised models and a launcher;
only the key's absolute path is written to the config.

```console
KEY_FILE="$CLIENT_DIR/alice.key"  # Choose your user's local key file.
umask 077
chmod 600 "$KEY_FILE"
curl --fail --cacert "$CLIENT_DIR/ca.pem" "$GATEWAY_URL/v1/models" \
  -o "$CLIENT_DIR/models.json"
jq --arg base "$GATEWAY_URL/v1" --arg key "{file:$KEY_FILE}" \
  --arg model "$MODEL" '
  {provider: (reduce .data[] as $m ({};
    reduce $m.praxis.apis[] as $api (. ;
      if ($api == "openai" or $api == "anthropic") then
        ("praxis-" + $api) as $id |
        .[$id] //= {name: $id,
          npm: (if $api == "anthropic" then "@ai-sdk/anthropic" else "@ai-sdk/openai-compatible" end),
          options: {baseURL: $base, apiKey: $key}, models: {}} |
        .[$id].models[$m.id] = {name: $m.id,
          limit: {context: $m.praxis.context, output: $m.praxis.output}} |
        ($m.praxis.upstream_model | ascii_downcase) as $upstream |
        if $api == "openai" and
          (($upstream | test("^(gpt-5|gpt-6|o1|o3|o4)")) or
           ($m.praxis.provider == "vllm" and ($upstream | contains("qwen")))) then
          .[$id].models[$m.id] += {provider: {npm: "@ai-sdk/openai"}, reasoning: true,
            options: {store: false, reasoningEffort: "medium", include: ["reasoning.encrypted_content"]}}
        elif $api == "openai" and ($upstream | contains("qwen")) then
          .[$id].models[$m.id] += {reasoning: true, interleaved: {field: "reasoning"}}
        else . end
      else . end))), disabled_providers: []} |
  .enabled_providers = (.provider | keys) |
  .model = ((first(["praxis-openai", "praxis-anthropic"][] as $id | select(.provider[$id].models[$model]) | $id)
    // error("Selected model is missing")) + "/" + $model)
' "$CLIENT_DIR/models.json" > "$CLIENT_DIR/opencode.json"
python3 -c '
import pathlib, shlex, sys
directory = pathlib.Path(sys.argv[1]).resolve()
launcher = directory / "opencode"
command = ["env", "NODE_EXTRA_CA_CERTS=" + str(directory / "ca.pem"),
           "OPENCODE_CONFIG=" + str(directory / "opencode.json"), "opencode"]
launcher.write_text("#!/bin/sh\nunset OPENCODE_CONFIG_CONTENT\nexec " + shlex.join(command) + " \"$@\"\n")
launcher.chmod(0o700)
print("\nRun this from any project directory, without exporting variables:\n")
print(shlex.quote(str(launcher)))
' "$CLIENT_DIR"
```

Run the printed launcher path from any project directory:

```console
/absolute/path/to/client-directory/opencode
```

It loads the saved config and CA without exports. Regenerate after model changes.
To switch users, regenerate with another `KEY_FILE`; after rotation, replace the
referenced key file and restart OpenCode. Keep keys outside project repositories.

</details>

<details>
<summary>Resulting OpenCode config — two-model example</summary>

Inspect your generated file with `jq . "$CLIENT_DIR/opencode.json"` in the setup
shell. It uses your URL, key path and model limits; for example:

```json
{
  "provider": {
    "praxis-openai": {
      "name": "praxis-openai",
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "https://gateway.example:8443/v1",
        "apiKey": "{file:/absolute/path/to/alice.key}"
      },
      "models": {
        "openai/gpt-5.4-mini": {
          "name": "openai/gpt-5.4-mini",
          "limit": {"context": 400000, "output": 128000},
          "provider": {"npm": "@ai-sdk/openai"},
          "reasoning": true,
          "options": {
            "store": false,
            "reasoningEffort": "medium",
            "include": ["reasoning.encrypted_content"]
          }
        }
      }
    },
    "praxis-anthropic": {
      "name": "praxis-anthropic",
      "npm": "@ai-sdk/anthropic",
      "options": {
        "baseURL": "https://gateway.example:8443/v1",
        "apiKey": "{file:/absolute/path/to/alice.key}"
      },
      "models": {
        "external/claude-sonnet-5": {
          "name": "external/claude-sonnet-5",
          "limit": {"context": 128000, "output": 8192}
        }
      }
    }
  },
  "disabled_providers": [],
  "enabled_providers": ["praxis-anthropic", "praxis-openai"],
  "model": "praxis-openai/openai/gpt-5.4-mini"
}
```

Both providers reference the same private user-key file. GPT uses the Responses
SDK; Messages uses the Anthropic SDK. The launcher supplies the CA separately.

</details>

<details>
<summary>Use the standard config directory and run just opencode</summary>

First generate the config using the **Save native configuration** block above.
Then run in the **workstation setup shell**. If a global JSON/JSONC config exists,
merge the generated settings into it instead; this block refuses to overwrite it.

```console
(
  set -e
  CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/opencode"
  mkdir -p "$CONFIG_DIR"
  if [ -e "$CONFIG_DIR/opencode.json" ] || [ -e "$CONFIG_DIR/opencode.jsonc" ]; then
    printf 'Existing OpenCode config: merge the generated settings instead.\n'
    exit 1
  fi
  cp "$CLIENT_DIR/opencode.json" "$CONFIG_DIR/opencode.json"
  chmod 600 "$CONFIG_DIR/opencode.json"
)
```

For the default private certificate, configure its CA once (**zsh on macOS**):

```console
printf '\nexport NODE_EXTRA_CA_CERTS=%q\n' "$CLIENT_DIR/ca.pem" >> "$HOME/.zshrc"
export NODE_EXTRA_CA_CERTS="$CLIENT_DIR/ca.pem"
unset OPENCODE_CONFIG OPENCODE_CONFIG_CONTENT
```

For Bash, use `~/.bashrc`. Preserve any existing CA bundle you need. Skip this
CA setting for a publicly trusted certificate; never disable TLS verification.

Then, in this shell or a newly opened project shell:

```console
cd /path/to/your/project
opencode
```

To switch users, change `options.apiKey` in both Praxis providers to the other
user's `{file:/absolute/path/to/key}`, then restart. Refresh the global config
when models change. Project settings can override global settings.

[Config locations and precedence](https://opencode.ai/docs/config/#precedence-order) ·
[Custom certificates](https://opencode.ai/docs/network/#custom-certificates)

</details>

## Operations

[Providers](providers.md) · [Users, keys and budgets](users.md) ·
[Manual installation](manual.md) · [Mock benchmarks](../../testing/pricetag-perf.md)

**Pilot limits:** keep this host restricted to trusted administrators. MaaS
management stays private. Keys expire within 90 days; revoking a key does not
end an existing dashboard session. Retention, upgrades and recovery still need
qualification. [Details](users.md#limits)
