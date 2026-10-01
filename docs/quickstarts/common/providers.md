# Manage providers in an existing Praxis gateway

Run as the administrator, from the matching deployment checkout. These commands
preserve other providers and listener authentication. Provider changes restart
Praxis; finish active tasks first. Valkey quotas persist across restarts.

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
speak the native API used by the harness: Responses for Codex, Chat Completions
for OpenCode, or Messages for Claude Code. The helper does not translate APIs.

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

## Client URLs and models

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
| Enabled providers, custom URLs, secret references | `/etc/praxis/providers.json` |
| Rendered routes, filters and quotas | `/etc/praxis/shared-gateway.yaml` |
| Capacity overrides | `/etc/praxis/quota-overrides.json` |
| Upstream keys | Rootless Podman secrets owned by `praxis-svc` |
| Harness models and menus | User-owned CLI configuration files |

Use the helpers for provider and capacity changes; hand edits to managed files
are rejected as configuration drift. Upgrades retain custom providers and the
shared-vLLM setting. Failed activation restores configuration from
`/etc/praxis/rollback/`. A failed quota migration never overwrites a shared ledger;
inspect its reported recovery state before retrying.
