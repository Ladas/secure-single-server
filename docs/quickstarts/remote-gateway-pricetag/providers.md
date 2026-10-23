# Provider configuration

The installer prompts for provider credentials. Use these commands over SSH
for later changes:

```console
cd ~/secure-single-server
sudo python3 scripts/pricetag/providers openai --replace
sudo python3 scripts/pricetag/providers external --api both --replace
```

Run only the command for the provider you want to change. Credentials use
hidden prompts; replacement preserves users, budgets and spending history.

| Provider | Input | Model prefix |
| --- | --- | --- |
| OpenAI | OpenAI key | `openai/` |
| External API provider | Endpoint(s) and a key for the selected API(s) | `external/` |

External provider setup adds HTTPS and the OpenAI `/v1` path automatically.
Choose `--api openai`, `--api anthropic`, or `--api both`. Only selected APIs
are discovered and configured. Check the printed
credential destinations before entering the key. [Back to installation](README.md)

<details>
<summary>Initial manual configuration</summary>

Run one or both setup commands, then export. Continue with
[manual installation](manual.md#3-start-services).

```console
sudo python3 scripts/pricetag/providers openai
sudo python3 scripts/pricetag/providers external --api both
sudo python3 scripts/pricetag/providers export
```

</details>

<details>
<summary>Separate Messages and OpenAI-compatible endpoints</summary>

```console
sudo python3 scripts/pricetag/providers external --api both --replace \
  --anthropic-url MESSAGES_HOST --openai-url OPENAI_COMPATIBLE_HOST
```

Use API origins, not an inference path such as `/v1/messages`.

</details>

<details>
<summary>Unattended installation with protected credential files</summary>

On the fresh RHEL server, provision keys into a root-owned `0700` directory.
Each file must be root-owned, mode `0400` or `0600`, with one credential line.
Pass paths, never key values:

```console
cd ~/secure-single-server
sudo scripts/pricetag/install --mode real --hostname GATEWAY_IP_OR_DNS \
  --provider openai --provider external --external-api both \
  --openai-key-file /root/provider-keys/openai.key \
  --external-key-file /root/provider-keys/external.key \
  --external-messages-url MESSAGES_HOST --external-openai-url OPENAI_COMPATIBLE_HOST --monthly-usd 5 --yes
```

For a shared hostname, use it for both endpoint options. For a single API,
select it with `--external-api` and provide only its endpoint.
Input files remain under your control after import; remove staged copies through
your secret-delivery process. Do not put credentials in Git or shell arguments.

### Configure providers from private files

Provision keys through your protected secret-delivery process into a root-owned
`0700` directory. Files must be root-owned regular files with mode `0400` or
`0600`, containing one credential line. Do not put values in argv, shell history,
Git, logs or environment assignments. Use an SSH session without agent forwarding.

```console
sudo python3 scripts/pricetag/providers openai \
  --key-file /root/provider-keys/openai.key
sudo python3 scripts/pricetag/providers external --api both \
  --anthropic-url MESSAGES_HOST --openai-url OPENAI_COMPATIBLE_HOST \
  --key-file /root/provider-keys/external.key
sudo python3 scripts/pricetag/providers export
```

The helper passes each key to Podman through stdin. It does not delete the input
file; remove staged copies through your secret-delivery process after confirming
successful configuration. The [installer](README.md#2-copy-and-install)
accepts the same protected files for a complete unattended fresh installation.


</details>

<details>
<summary>Missing models, discovery errors and changed catalogs</summary>

### Discovery options

The helper selects reviewed presets, not every advertised model. Each selected
external API must advertise at least one matching preset; choose only the APIs
your endpoint supports. A catalog may
omit models permitted for a key; missing entries do not prove inference is
unavailable. Conversely, discovery success does not prove inference works.

```console
sudo python3 scripts/pricetag/providers external --api both --check-auth --debug
sudo python3 scripts/pricetag/providers external --help
```

`--debug` prints URLs, header names and status codes without keys or response
bodies. `--catalog-auth` changes only discovery authentication;
`--messages-auth` changes the Messages credential header. Follow your provider's
credential documentation rather than trying to bypass an HTTP 401.

Use `--pin-model API:MODEL` only for a reviewed preset that your provider supports.
Use `--check-inference API:MODEL` to make a bounded real request (up to 16 output
tokens); it can incur upstream charges. Both options accept `anthropic` or
`openai` as the API. See `configs/pricetag/provider-models.json` for accepted IDs,
limits and price-source mappings. Unsupported models need reviewed metadata and
pricing before being added. `--allow-unverified-models` permits presets after
catalog HTTP 404/405/501 only; authentication and TLS failures still stop setup.


To replace the external model selection as well as its endpoint/key:

```console
sudo python3 scripts/pricetag/providers external --api both --replace --refresh-models --debug
```

Review model limits and prices before sending real traffic. A failed activation
attempts rollback; old secrets remain available for recovery. Do not rerun
`prepare.py` for provider replacement. Historical usage is not repriced.

</details>

<details>
<summary>Existing deployments using the pricetag provider name</summary>

Use `scripts/pricetag/providers pricetag --replace` for a deployment originally
created with `pricetag/` aliases. That legacy profile and its endpoint-pair
normalization remain supported. New `external` profiles use `external/` aliases;
changing the profile name is not an in-place key rotation.

</details>
