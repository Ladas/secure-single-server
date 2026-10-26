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
  "cd ~/secure-single-server && sudo scripts/pricetag/install --mode real --hostname '$GATEWAY_HOST'"
```

Choose **OpenAI directly**, an **external API provider**, or **both**. At least
one is required. For the external provider, choose **OpenAI-compatible**,
**Anthropic Messages**, or **both APIs**, then enter the endpoint(s) and key.
Keys use hidden prompts. One external key must cover all selected external APIs.

The installer validates credentials and selects supported model presets before
building anything. Review the displayed setup and type `install` to continue;
no more prompts are needed. A rejected key stops setup without saving provider
configuration—correct it and rerun the command.

Installation shows six stages and progress messages. Detailed command output
goes to the private `/var/log/praxis-install-*.log` file printed at startup;
use the displayed `sudo tail -f` command in another SSH session to follow it.
On failure, the installer prints the failed stage and log command. Keep the
log private; review it before sharing. **Use published images** is the default:
MaaS and PriceTag are pulled by their qualified digests, without compiling Go.
Choose **Build from source** to test a branch or commit; builds can take several minutes.
[Image options and testing new versions](images.md)

It creates `admin`, `alice` and `bob`; Alice and Bob each get $5/month. Real mode
cannot defer provider setup or omit these initial users. For a different
allowance, add `--monthly-usd 10`. For a DNS certificate, set `GATEWAY_HOST` to
that DNS name before installation. Existing deployments are refused.

[Manual installation](manual.md) · [Provider options and unattended setup](providers.md)

## 3. Open the dashboards

Print the browser URL and the saved keys over SSH:

```console
printf 'https://%s:8443/login\n' "$GATEWAY_HOST"
ssh "${SSH_OPTS[@]}" "$RHEL_HOST" \
  'for user in admin alice bob; do printf "\n%s: " "$user"; sudo cat "/root/pricetag-admin/$user.key"; printf "\n"; done'
```

Open that URL, trust the deployment certificate and paste the admin key.
Ordinary users can log in, but their personal dashboards are pending upstream
and currently show “coming soon.” Use the administrator dashboard to inspect usage.
[Create users, set budgets and rotate keys](users.md)

## 4. Prepare the local connection

Run this once in the **workstation shell used for installation**. It copies
the CA and Alice's key, asks for a starting model, then prints the environment
variables and command for launching OpenCode dynamically from any project shell:

```console
cd "$REPO"
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
printf 'Initial model alias: '
IFS= read -r MODEL
printf '\nCopy into any workstation shell opened in your project directory:\n\n'
printf 'export REPO=%q\nexport CLIENT_DIR=%q\nexport GATEWAY_URL=%q\nexport MODEL=%q\n' \
  "$REPO" "$CLIENT_DIR" "$GATEWAY_URL" "$MODEL"
printf '%s\n' \
  'python3 "$REPO/scripts/pricetag/harness" opencode \' \
  '  --url "$GATEWAY_URL" --key-file "$CLIENT_DIR/alice.key" \' \
  '  --ca-file "$CLIENT_DIR/ca.pem" --model "$MODEL"'
```

The printed block contains connection settings and file paths, not key contents.

## 5. Run OpenCode

Open a **shell in your project directory** and paste the block printed above.
Reuse it in other project shells to run separate sessions. The helper refreshes
the model list on each launch; all enabled models appear in the picker.
Sessions share Alice's budget and leave saved OpenCode configuration unchanged.

For later launches without exporting variables, save the configuration and
launcher below once.

<details>
<summary>Save native configuration and a launcher — no exports needed on later runs</summary>

The helper reads `/v1/models`, groups aliases by OpenAI or Anthropic API, and
copies their context/output limits. It supplies the key and CA for this process
and launches OpenCode using `OPENCODE_CONFIG_CONTENT`. It does not install
OpenCode, issue keys or modify saved OpenCode settings.

Run this once in the **workstation shell used for setup**, where the variables
from step 4 remain set. It needs `jq` and saves all advertised models plus a
launcher. **Choose the user key on the first line**: keep Alice's path or replace
it with the absolute path to a custom user's local key file. Use an inference
key, not the admin key; requests use the selected user's budget. The key stays
in that private file—only its path is saved in OpenCode configuration.

```console
KEY_FILE="$CLIENT_DIR/alice.key"  # Or an absolute path to your custom user's key file.
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
          limit: {context: $m.praxis.context, output: $m.praxis.output}}
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

Copy the printed launcher path into any project shell to start OpenCode there.
It loads the saved configuration and CA automatically; no repository path or
shell exports are needed. Other OpenCode invocations are unaffected.

Rerun this setup block when the server's models change or to select another key
path. After key rotation, securely replace the contents of the selected local
key file and restart OpenCode. Never commit key files to a project repository.
OpenCode still merges unrelated settings from
your existing configuration. For a hand-maintained catalog, edit
`opencode.json` instead of regenerating it.
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
