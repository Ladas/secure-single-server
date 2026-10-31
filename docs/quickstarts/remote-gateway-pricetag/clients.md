# OpenCode: manual configuration and desktop

Use the [dynamic launch](README.md#6-run-opencode) for a fresh catalog on every
start. Expand an option below to save a configuration, configure OpenCode
manually, or connect the desktop app.
First complete [local connection setup](README.md#5-prepare-the-local-connection);
these examples use its workstation shell variables.

<details markdown="1">
<summary>Save native configuration and a launcher — no exports needed on later runs</summary>

Run in the **workstation setup shell** after connection setup. Requires `jq`.
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
        elif $api == "anthropic" and
          ($upstream | test("^claude-((opus|sonnet)-(4-[678]|5)(-|$)|haiku-5(-|$))")) then
          .[$id].models[$m.id].options = {thinking: {type: "adaptive", blockBinding: false}}
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

<details markdown="1">
<summary>Manual config — direct OpenAI and external OpenAI/Messages</summary>

Inspect your generated file with `jq . "$CLIENT_DIR/opencode.json"` in the setup
shell, or save the example below as your private `opencode.json` without using
our helper. Replace the gateway URL and key path. Include only aliases advertised
by your gateway and copy their `praxis.context` / `praxis.output` values from
`/v1/models`; these example limits are not discovery from the upstream provider.

`praxis-openai` groups both direct `openai/` and external `external/` aliases by
API dialect. `praxis-anthropic` handles external Messages aliases. These are
connections to Praxis, not direct connections to the upstream services.

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
        },
        "external/gpt-5.4-mini": {
          "name": "external/gpt-5.4-mini",
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
        "external/claude-sonnet-5-5": {
          "name": "external/claude-sonnet-5-5",
          "limit": {"context": 1000000, "output": 128000},
          "options": {"thinking": {"type": "adaptive", "blockBinding": false}}
        }
      }
    }
  },
  "disabled_providers": [],
  "enabled_providers": ["praxis-anthropic", "praxis-openai"],
  "model": "praxis-openai/openai/gpt-5.4-mini"
}
```

Save this file outside your project repository and protect it and the key with
`chmod 600`. To run directly from a project shell:

```console
NODE_EXTRA_CA_CERTS=/absolute/path/to/ca.pem \
OPENCODE_CONFIG=/absolute/path/to/opencode.json opencode
```

Both providers reference the same private user-key file. GPT uses the Responses
SDK; Messages uses the Anthropic SDK. The launcher supplies the CA separately.

</details>

<details markdown="1">
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

<details markdown="1">
<summary>External Claude rejects thinking.adaptive.block_binding</summary>

OpenCode may inject a thinking extension that an Anthropic-compatible gateway
rejects. The helper sets this compatibility option for recognized adaptive-thinking
Claude models, using upstream model metadata rather than the public alias:

```json
"options": {
  "thinking": { "type": "adaptive", "blockBinding": false }
}
```

This retains adaptive thinking and omits the unsupported binding field. It does
not change authentication, routing or model limits. Verified with OpenCode 1.19.5;
[upstream opt-out](https://github.com/anomalyco/opencode/pull/46820).
Restart the helper for a session config, or regenerate a saved native config
before restarting OpenCode. This is a workstation change; no gateway rebuild is
needed. OpenCode 2 requires separate qualification because its compatibility
configuration differs ([tracked issue](https://github.com/anomalyco/opencode/issues/52325)).

</details>

<details markdown="1">
<summary>OpenCode Desktop — use a local server with explicit CA trust</summary>

Use the saved config above. Start the installed OpenCode CLI backend from your
project directory; keep this shell running. This makes CA handling explicit
instead of depending on whether a Finder-launched app inherits shell variables.

```console
cd /path/to/your/project
unset OPENCODE_CONFIG_CONTENT
export OPENCODE_CONFIG=/absolute/path/to/opencode.json
export NODE_EXTRA_CA_CERTS=/absolute/path/to/ca.pem
export NO_PROXY=localhost,127.0.0.1
export OPENCODE_SERVER_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
printf %s "$OPENCODE_SERVER_PASSWORD" | pbcopy  # macOS: copy the local-server password
opencode serve --hostname 127.0.0.1 --port 4096
```

In **OpenCode Desktop → server picker**, add `http://127.0.0.1:4096` with username
`opencode` and the generated server password (copied to the clipboard on macOS).
On other platforms, use your password manager or clipboard tool before starting
`serve`.

This password protects the local OpenCode backend; it is separate from the user
key in your config. Clear the clipboard afterward. The backend connects to Praxis
using HTTPS and the configured CA. Do not enter the gateway URL as the desktop's
OpenCode server URL, and do not bind this backend to a public interface.

Choose a project and a gateway model in the desktop app. Use compatible CLI and
desktop versions; the gateway configuration was qualified with OpenCode 1.19.5,
not OpenCode 2. Desktop interaction still needs a manual smoke test on your
installed version. Switch users by changing both provider key-file references,
then restarting the backend.

[Desktop server selection](https://opencode.ai/docs/troubleshooting/#fix-server-connection-issues) ·
[Server authentication](https://opencode.ai/docs/server/#authentication) ·
[CA trust](https://opencode.ai/docs/network/#custom-certificates)

</details>
