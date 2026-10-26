# Providers and models

Provider credentials stay on RHEL; clients authenticate with their own user keys.
The helper has two fixed profiles:

| Profile | Supported upstream API | Gateway model aliases |
| --- | --- | --- |
| `openai` | OpenAI directly | `openai/MODEL_ID` |
| `external` | OpenAI-compatible Chat/Responses, Anthropic Messages, or both | `external/MODEL_ID` |

An external provider is a hosted service or another gateway. Select its supported
API(s); both may share a host, but must accept the same key. Enter an API origin:
HTTPS and `/v1` normalization are automatic. GPT Responses models require
`/v1/responses`, not just Chat compatibility.

**Limits:** no arbitrary profile names, multiple external keys, or adding another
provider after installation. Choose needed profiles at install time. Legacy
`pricetag/` deployments continue using the `pricetag` command.

## Open the management session

From the **workstation shell used for installation**:

```console
ssh -t "${SSH_OPTS[@]}" "$RHEL_HOST" \
  'cd ~/secure-single-server && exec bash'
```

Run operations below in **this SSH session**; `exit` returns to your workstation.
New shell? Restore [connection variables](README.md#1-set-the-connection) first.

## List configured providers and enabled models

```console
sudo python3 scripts/pricetag/providers list
```

Lists prepared profiles, enabled aliases, APIs and limits; never keys.

## List available external models

Run on **RHEL**. Enter the endpoint(s) and credential at the hidden prompt:

```console
sudo python3 scripts/pricetag/providers external --api both --list-models
```

Shows upstream IDs, context/output limits, their source and the config-file path.
Nothing is saved. Use `--api openai` or `--api anthropic` for a single API.
For pasteable JSON, follow [Extend the model configuration](#extend-the-model-configuration).

<details>
<summary>Search, pagination and direct OpenAI discovery</summary>

```console
sudo python3 scripts/pricetag/providers external --api both --list-models --search claude
sudo python3 scripts/pricetag/providers openai --list-models --search gpt --page 1 --page-size 20
```

Search matches model IDs case-insensitively. Interactive pages show 20 models:
Enter continues; `q` stops. `--page N` selects one page; `--all` prints all matches.

Search/display pagination are local; upstream cursor pages are fetched first.
OpenAI's standard catalog has no name-search parameter or token limits.
Anthropic can return limits; compatible gateways may omit them.
[OpenAI API](https://developers.openai.com/api/reference/resources/models/methods/list) ·
[Anthropic API](https://platform.claude.com/docs/en/api/models/list)

</details>

## Replace a key or endpoint

Run only the command for your existing provider:

```console
sudo python3 scripts/pricetag/providers openai --replace
```

```console
sudo python3 scripts/pricetag/providers external --api both --replace
```

Enter the new endpoint/key. Models, users, budgets and usage are preserved.
Praxis restarts; failed readiness triggers attempted rollback. Do not rerun `prepare.py`.

<details>
<summary>Specify separate external endpoints</summary>

```console
sudo python3 scripts/pricetag/providers external --api both --replace \
  --anthropic-url MESSAGES_HOST --openai-url OPENAI_COMPATIBLE_HOST
```

Check the printed credential destinations before entering the key.

</details>

## Extend the model configuration

Run these steps in the **RHEL management session**.

**1. Print pasteable JSON for the external provider.**

```console
sudo python3 scripts/pricetag/providers external --api both --list-models --all --format config
```

Add `--search claude` (or another substring) to narrow the output. Copy only the
JSON rows you want. Models with unknown limits are omitted; obtain verified
limits before adding them manually. Local preset limits are not confirmation
of the hosted service's limits.

**2. Merge those rows into the preset JSON.**

```console
cd ~/secure-single-server
cp -p configs/pricetag/provider-models.json configs/pricetag/provider-models.json.bak
vi configs/pricetag/provider-models.json
python3 -m json.tool configs/pricetag/provider-models.json >/dev/null
```

Paste each row into its matching `openai` or `anthropic` array, separating rows
with commas. Keep existing rows you still need; do not replace the whole file
with a filtered/page fragment. Avoid duplicate IDs within an API array.

Row format: `["UPSTREAM_MODEL_ID", context_tokens, max_output_tokens]`.
Do not add gateway prefixes such as `external/`; the helper adds them.

<details>
<summary>Example JSON — keep only the models you want</summary>

```json
{
  "openai": [
    ["gpt-5.4-mini", 400000, 128000],
    ["gpt-6-luna", 1050000, 128000]
  ],
  "anthropic": [
    ["claude-sonnet-5-5", 1000000, 128000]
  ]
}
```

The sections select **APIs**, not provider profiles. `openai` presets are shared
by direct OpenAI and the external OpenAI-compatible API; `anthropic` presets
apply to external Messages. Editing this file alone does not change a running
gateway. Separate per-provider preset files are not supported.

</details>

**3. Apply the external selection and check enabled models.**

```console
sudo python3 scripts/pricetag/providers external --api both --replace --refresh-models
sudo python3 scripts/pricetag/providers list
```

Enter the intended endpoint(s) and key again. This enables advertised presets
plus explicit pins, removes unselected external models, and restarts Praxis.
Other providers, users and historical spending remain unchanged.

**4. Refresh OpenCode on your workstation.** Restart the dynamic helper, or
regenerate saved configuration. See [Refresh local OpenCode](#refresh-local-opencode).

**Before adding a new model:** verify its API and limits, and ensure PriceTag
has a reviewed price under the exact upstream ID. Activation refuses a new alias
without that source price; do not use a zero-price placeholder. JSON validation
above checks syntax only. Do not edit generated `/etc/praxis-pricetag` files.

**Direct OpenAI:** edit presets before initial installation. Live model refresh
is not implemented for this profile; `openai --replace` retains its existing
models. Editing the preset JSON does not bypass that limitation.

<details>
<summary>Include a reviewed model omitted from discovery</summary>

Replace `MODEL_ID` with an exact ID from the presets and choose its API:

```console
sudo python3 scripts/pricetag/providers external --api both --replace --refresh-models \
  --pin-model anthropic:MODEL_ID
```

Repeat `--pin-model` for additional models. A pin does not prove entitlement.
Test a reviewed model with a small, billable request before relying on it:

```console
sudo python3 scripts/pricetag/providers external --api both \
  --check-inference anthropic:MODEL_ID
```

The diagnostic requests at most 16 output tokens and changes no configuration.

</details>

<details>
<summary>Current presets and limit sources</summary>

The preset selection includes GPT-5.4 mini, GPT-6 Luna, GPT-6.1 Sol, GPT-6 Astra,
Claude Sonnet/Opus/Haiku 5.5, GLM 5.3 and DeepSeek V4.1 Flash 1017. GLM and
DeepSeek are listed under both APIs; availability still depends on discovery.
Old Claude presets and the unavailable Qwen preset are removed on external
model refresh. Direct OpenAI's existing selection is unchanged by that command.

| Updated presets | Context / maximum output | Source |
| --- | --- | --- |
| GPT-6 Astra | 1,050,000 / 128,000 | [OpenAI](https://developers.openai.com/api/docs/models/gpt-6-astra) |
| Claude Sonnet/Opus/Haiku 5.5 | 1,000,000 / 128,000 | [Sonnet](https://platform.claude.com/docs/en/models/sonnet-5-5/overview), [Opus](https://platform.claude.com/docs/en/models/opus-5-5/overview), [Haiku](https://platform.claude.com/docs/en/models/haiku-5-5/overview) |
| DeepSeek V4.1 Flash 1017 | 1,000,000 / 384,000 | [DeepSeek](https://api-docs.deepseek.com/quick_start/pricing/) |

These are manufacturer-based preset ceilings, not verified limits of an external
hosted deployment. Lower them if the provider documents smaller limits. Existing
GLM settings remain 262,144 / 65,536. Pricing must exist independently in PriceTag;
a model catalog does not supply a verified price.

</details>

## Refresh local OpenCode

On your **workstation**, restart the [dynamic helper](README.md#5-run-opencode)
to refresh models. For saved config, regenerate it. If the default model was
removed, select another alias or repeat step 4. Keep the intended `KEY_FILE`;
upstream credential changes do not require new user keys.

<details>
<summary>Discovery errors and authentication headers</summary>

```console
sudo python3 scripts/pricetag/providers external --api both --check-auth --debug
sudo python3 scripts/pricetag/providers external --help
```

`--debug` prints URLs, header names and statuses without credentials or response
bodies. `--catalog-auth` changes discovery authentication only;
`--messages-auth` selects the Messages inference header. Follow the upstream's
credential instructions. Authentication and TLS errors stop setup.

`--allow-unverified-models` permits presets when discovery returns HTTP
404/405/501. Use it only after confirming the endpoint and model access;
it does not bypass authentication failures.

</details>

<details>
<summary>Manual initial setup and unattended credentials</summary>

On a fresh host prepared using [manual installation](manual.md), run one or both
commands, then export and continue with service startup:

```console
sudo python3 scripts/pricetag/providers openai
sudo python3 scripts/pricetag/providers external --api both
sudo python3 scripts/pricetag/providers export
```

For automation, provision one-line credentials in root-owned regular files,
mode `0400` or `0600`, inside a root-owned `0700` directory. Pass paths, never
values. The helper imports keys into Podman through stdin.

```console
sudo scripts/pricetag/install --hostname GATEWAY_IP_OR_DNS \
  --provider openai --provider external --external-api both \
  --openai-key-file /root/provider-keys/openai.key \
  --external-key-file /root/provider-keys/external.key \
  --external-messages-url MESSAGES_HOST --external-openai-url OPENAI_COMPATIBLE_HOST \
  --no-sample-users --monthly-usd 5 --yes
```

Use the same hostname for both external options if appropriate. Remove unused
provider options for a single-provider install. Provider commands also accept
`--key-file /root/provider-keys/NAME.key`. Staged files are not automatically
deleted; remove them through your secret-delivery process after verification.

</details>
