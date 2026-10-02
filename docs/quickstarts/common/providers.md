# Manage providers in an existing Praxis gateway

Run as the administrator, from the matching deployment checkout. These commands
preserve other providers and listener authentication. Provider changes restart
Praxis; finish active tasks first. Valkey quotas persist across restarts.
For a new Qwen installation, first complete [vLLM setup](vllm.md). Then use the
shared quota and unified catalog below; cloud providers are optional additions.

**Contents:** [OpenAI](#openai) · [Anthropic](#anthropic) ·
[Compatible provider](#another-compatible-provider) · [Shared vLLM quota](#share-the-local-vllm-quota-across-harnesses) ·
[Unified models](#unified-models-all-in-one) · [Operations](#inspect-rotate-and-disable)

```console
cd ~/secure-single-server-deploy
sudo dnf install -y python3-pyyaml
sudo scripts/common/providers show
sudo scripts/common/quota-set --list
```

## OpenAI

```console
sudo scripts/common/providers enable openai
sudo scripts/common/quota-set --provider openai --capacity 2000000
sudo scripts/common/quota-set --provider openai --capacity 2000000 --apply
```

Enter the key at the hidden prompt. It becomes a versioned Podman secret; it is
never passed in command arguments or given to harness users. The quota is an
independent rolling 24-hour token allowance shared by this provider's users.

## Anthropic

```console
sudo scripts/common/providers enable anthropic
sudo scripts/common/quota-set --provider anthropic --capacity 2000000 --apply
```

## Another compatible provider

Choose a unique lowercase name and replace the example URL. The upstream must
speak the native API used by the harness: Responses for Codex, Messages for
Claude Code, or the selected SDK's API for OpenCode. The unified OpenCode
configuration uses Responses for GPT and local Qwen. There is no API translation.

```console
sudo scripts/common/providers enable team \
  --openai-url https://openai.example.com/v1
sudo scripts/common/quota-set --list --provider team
sudo scripts/common/quota-set --provider team --capacity 2000000 --apply
```

If the same provider/key also supports native Anthropic Messages, supply both
endpoints when enabling it:

```console
sudo scripts/common/providers enable team \
  --openai-url https://openai.example.com/v1 \
  --anthropic-url https://messages.example.com
```

This prompts for the provider key again. Use separate provider names when the
two endpoints require different keys. URLs must use HTTPS and an origin or
`/v1` path; other upstream path prefixes are not supported by this helper.
With both APIs enabled, `team-openai-rolling-day` and
`team-anthropic-rolling-day` are independent quotas; `--provider team` selects
both. Direct OpenAI, Anthropic and local vLLM budgets remain independent.

## Share the local vLLM quota across harnesses

On a Valkey gateway:

```console
sudo scripts/common/providers enable vllm --shared-quota --capacity 10000000
sudo scripts/common/quota-set --list --provider vllm
sudo scripts/common/quota-status
```

This creates one `vllm-rolling-day` budget for Chat, Responses and Messages.
It migrates the two existing vLLM ledgers with their original timestamps and
retains charges for interrupted reservations. Old ledgers remain for recovery;
the allowance is the supplied capacity, not the sum of the former capacities.
Migration requires the pinned image and managed 24h/300s Valkey rules.
In-memory quotas cannot share a budget across the two all-in-one listeners.

## Unified models (all-in-one)

This opt-in mode replaces per-provider paths with two loopback endpoints:

| Client API | Base URL | Catalog |
| --- | --- | --- |
| Responses / Chat | `http://127.0.0.1:8080/v1` | `GET /v1/models` |
| Messages | Claude: `http://127.0.0.1:8081`; OpenCode: append `/v1` | `GET /v1/models` |

The model alias selects the provider. Praxis allows only configured aliases,
rewrites each to its upstream model ID, and applies that provider's credentials
and quota. Unknown aliases are rejected. Cloud budgets remain independent;
the shared vLLM budget covers both listeners. There is no automatic failover.
This mode currently supports all-in-one memory/Valkey gateways, not remote
HTTPS/JWT gateways or Switchyard.

### Create the catalog

For Qwen, select the installed preset. Change the first line to `qwen3-8b`
for 8B. Run once; an existing catalog is never overwritten:

```console
VLLM_MODEL=qwen3.8-27b-int4
sudo python3 - "$VLLM_MODEL" <<'PY'
import json, pathlib, sys
model = sys.argv[1]
context, output = {'qwen3-8b': (16384, 4096), 'qwen3.8-27b-int4': (32768, 8192)}[model]
entry = dict(id='vllm/' + model, provider='vllm', model=model,
             apis=['openai', 'anthropic'], context=context, output=output)
with pathlib.Path('/etc/praxis/unified-models.json').open('x') as f:
    json.dump([entry], f, indent=2)
    f.write('\n')
PY
```

### Choose cloud models and apply

Enable the desired providers above. Choose exact IDs available to your account
and confirm the required API: appearing in a model list does not prove Responses
or tool support. To query an OpenAI-compatible upstream catalog without reading
stored secrets, run in Bash and enter its HTTPS `/v1/models` URL and key:

```console
(
  set +x
  set -o pipefail
  IFS= read -r -p 'Upstream HTTPS models URL: ' models_url
  IFS= read -r -s -p 'API key: ' key; printf '\n'
  printf 'Authorization: Bearer %s\n' "$key" |
    curl --proto '=https' --fail --silent --show-error --connect-timeout 10 --max-time 60 \
      --header @- "$models_url" | python3 -m json.tool
)
```

For an Anthropic-native catalog:

```console
(
  set +x
  set -o pipefail
  IFS= read -r -p 'Upstream HTTPS models URL: ' models_url
  IFS= read -r -s -p 'API key: ' key; printf '\n'
  printf 'x-api-key: %s\nanthropic-version: 2023-06-01\n' "$key" |
    curl --proto '=https' --fail --silent --show-error --connect-timeout 10 --max-time 60 \
      --header @- "$models_url" | python3 -m json.tool
)
```

For direct OpenAI the URL is `https://api.openai.com/v1/models`; direct
Anthropic uses `https://api.anthropic.com/v1/models`.

Edit the non-secret JSON array. Add one object per approved model using this
shape, replacing the model ID and choosing supported client budgets:

```json
{
  "id": "openai/APPROVED_MODEL",
  "provider": "openai",
  "model": "APPROVED_MODEL",
  "apis": ["openai"],
  "context": 128000,
  "output": 8192
}
```

Use `provider: "anthropic"` with `apis: ["anthropic"]`, or the custom provider
name (`team`) and its supported API(s). `id` is a unique menu alias; `model` is
the exact upstream ID. Context includes input and output; set both within the
**served** limits. These are client hints, not gateway-enforced generation caps.
For a cloud-only gateway, create the array with approved cloud entries instead
of the Qwen block. The native-config helper currently needs an enabled model
on each API listener.

Edit, validate and apply together; then inspect the published catalogs:

```console
sudoedit /etc/praxis/unified-models.json &&
sudo scripts/common/providers unified --models /etc/praxis/unified-models.json --vllm-reasoning hide &&
sudo scripts/common/providers models
```

`--vllm-reasoning hide` keeps Qwen thinking enabled but omits plaintext reasoning
from its Responses output. This prevents that reasoning from breaking a later
cloud request. It does **not** make encrypted cloud reasoning acceptable to vLLM
on the return path. Messages and cloud output are unchanged.

Only entries with enabled provider backends are published. Upstream catalogs
never update this allowlist automatically. After each change, ordinary users
run `praxis-harness-config` and restart their CLIs; see [user setup](../all-in-one/users.md).

## Per-provider URLs (without unified mode)

Use these on remote gateways and existing all-in-one installations that have
not enabled unified models. They are replaced by the unified endpoints above.

| API | All-in-one origin | Path |
| --- | --- | --- |
| Local vLLM Chat/Responses | `http://127.0.0.1:8080` | `/vllm/v1` |
| Local vLLM Messages | `http://127.0.0.1:8081` | `/vllm` |
| Direct OpenAI | `http://127.0.0.1:8080` | `/v1` |
| Direct Anthropic | `http://127.0.0.1:8081` | no suffix |
| Custom OpenAI-compatible provider | `http://127.0.0.1:8080` | `/providers/team/v1` |
| Custom Messages provider | `http://127.0.0.1:8081` | `/providers/team` |

Claude appends `/v1/messages`. For a remote gateway, replace the origin with
the gateway's HTTPS origin and use a caller JWT. Provider keys stay on the server.
The gateway removes `/vllm` or `/providers/team` before forwarding.

List provider models from an all-in-one user session:

```console
curl --fail --silent --show-error http://127.0.0.1:8080/v1/models
curl --fail --silent --show-error http://127.0.0.1:8080/providers/team/v1/models
```

Choose exact model IDs supported by that account and API. Configure the user
menus with [harness configuration](harness-configuration.md). A configured menu
is not a server-side model allowlist and does not grant account access. There is
no aggregated gateway catalog. On a remote gateway, a provider with both APIs
uses its OpenAI catalog at the shared `/v1/models` path; configure Claude entries
explicitly there.

## Inspect, rotate and disable

```console
sudo scripts/common/providers show
sudo scripts/common/quota-status
sudo scripts/common/verify --host
```

Repeat `enable NAME` to rotate its key; saved custom URLs are retained. To reuse
an existing Podman secret, add `--secret NAME` instead of entering a new key.
To disable a provider while retaining its secret:

```console
sudo scripts/common/providers disable team
```

Keep at least one provider enabled. Local inference installation is separate;
see [vLLM installation](vllm.md).

## Where settings live

| Setting | Managed location |
| --- | --- |
| Enabled providers, custom URLs, secret references, applied catalog | `/etc/praxis/providers.json` |
| Administrator-edited non-secret model catalog | `/etc/praxis/unified-models.json` |
| Rendered routes, filters and quotas | `/etc/praxis/shared-gateway.yaml` |
| Capacity overrides | `/etc/praxis/quota-overrides.json` |
| Upstream keys | Rootless Podman secrets owned by `praxis-svc` |
| Harness models and menus | User-owned CLI configuration files |

Use the helpers for provider and capacity changes; hand edits to managed files
are rejected as configuration drift. Upgrades retain custom providers and the
shared-vLLM setting and applied unified catalog. Failed activation restores configuration from
`/etc/praxis/rollback/`. A failed quota migration never overwrites a shared ledger;
inspect its reported recovery state before retrying.
