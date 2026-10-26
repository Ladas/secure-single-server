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

<details>
<summary>List models advertised by an upstream</summary>

Choose a provider. Enter its endpoint(s) and hidden key; nothing is saved.

```console
sudo python3 scripts/pricetag/providers openai --list-models
```

```console
sudo python3 scripts/pricetag/providers external --api both --list-models
```

Replace `both` with `openai` or `anthropic` for a single API. Catalogs can depend
on the credential and may omit usable models; listing is not an inference test.

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

## Enable more models

Enabled models must be advertised **and** present in the
[reviewed presets](../../../configs/pricetag/provider-models.json). Refresh an
existing external provider:

```console
sudo python3 scripts/pricetag/providers external --api both --replace --refresh-models
sudo python3 scripts/pricetag/providers list
```

This replaces that provider's selection with the currently advertised presets;
models no longer advertised are removed unless explicitly pinned. Other
providers and historical spending remain unchanged.

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

New presets require reviewed API/limit metadata and a metering price source.
Direct OpenAI model refresh is unsupported; `openai --replace` retains models.

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
