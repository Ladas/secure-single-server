# Providers and models

A provider is an upstream inference service. Its credential stays on RHEL;
clients use their own MaaS user keys to reach the gateway.

The setup helper has two fixed profiles:

| Profile | Supported upstream API | Gateway model aliases |
| --- | --- | --- |
| `openai` | OpenAI directly | `openai/MODEL_ID` |
| `external` | OpenAI-compatible Chat/Responses, Anthropic Messages, or both | `external/MODEL_ID` |

An external provider may be a hosted model service or another gateway. Choose
only the APIs it implements. GPT models configured for Responses need a working
`/v1/responses` endpoint; Chat compatibility alone is insufficient. Both APIs may
share a hostname or use separate endpoints, but this profile uses **one key**.
HTTPS and the OpenAI `/v1` suffix are added automatically. Enter an API origin,
not a request path such as `/v1/messages`.

Arbitrary profile names, multiple external credentials and adding another
provider to an already running deployment are not supported by this helper.
Choose the required profiles during installation. Existing `pricetag/` deployments
retain the legacy `pricetag` profile; new installs use `external/`.

## Open the management session

From the **workstation shell used for installation**:

```console
ssh -t "${SSH_OPTS[@]}" "$RHEL_HOST" \
  'cd ~/secure-single-server && exec bash'
```

Run the following commands in that SSH session. If using a new workstation shell,
restore `RHEL_HOST`, `SSH_KEY` and `SSH_OPTS` from [connection setup](README.md#1-set-the-connection).
Type `exit` to return to your workstation when finished.

## List configured providers and enabled models

```console
sudo python3 scripts/pricetag/providers list
```

Shows each prepared provider, its model aliases, APIs and context/output limits.
It does not read or print provider keys. Only these configured models are
advertised to clients; the upstream may offer additional models.

## List models advertised by an upstream

Run the command for the provider to inspect. Enter its endpoint(s), if external,
and its key at the hidden prompt. Discovery does not save the key or change setup.

```console
sudo python3 scripts/pricetag/providers openai --list-models
```

```console
sudo python3 scripts/pricetag/providers external --api both --list-models
```

Replace `both` with `openai` or `anthropic` for a single API. Catalogs can depend
on the credential and may omit usable models; listing is not an inference test.

## Replace a key or endpoint

Run only the command for your existing provider:

```console
sudo python3 scripts/pricetag/providers openai --replace
```

```console
sudo python3 scripts/pricetag/providers external --api both --replace
```

Enter the replacement endpoint(s) and credential. This preserves existing model
selection, users, budgets and usage. It restarts Praxis and checks readiness;
a failed activation attempts rollback. Do not rerun `prepare.py`.

<details>
<summary>Specify separate external endpoints</summary>

```console
sudo python3 scripts/pricetag/providers external --api both --replace \
  --anthropic-url MESSAGES_HOST --openai-url OPENAI_COMPATIBLE_HOST
```

Check the printed credential destinations before entering the key.

</details>

## Enable more models

The helper enables the intersection of the upstream catalog and the reviewed
presets in [provider-models.json](../../../configs/pricetag/provider-models.json).
It does not automatically expose every model returned by `/models`.

To refresh an existing external provider's selection:

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

Models outside the presets need reviewed IDs, supported APIs, context/output
limits and a matching metering price source before deployment. Do not guess
limits or prices. Direct OpenAI model refresh is not implemented by this helper;
`openai --replace` only replaces credentials while retaining existing models.
These cases require a reviewed configuration change, not a dashboard toggle.

## Refresh local OpenCode

Exit SSH and return to the workstation. For the dynamic helper, close OpenCode
and rerun [Run OpenCode](README.md#5-run-opencode); each launch fetches the current
catalog. If the previous default was removed, set `MODEL` to an enabled alias or
rerun step 4 to select the first model.

For saved native configuration, rerun the expandable configuration block in
that section. Keep `KEY_FILE` pointed at the intended user's key. Provider
credential changes do not require new user keys.

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
sudo scripts/pricetag/install --mode real --hostname GATEWAY_IP_OR_DNS \
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
