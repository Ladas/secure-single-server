# Praxis token quotas

Use this scenario after a reviewed manual or bootc deployment is running. It
shows how an administrator can inspect enabled providers and a shared Praxis
token allowance, enable or rotate a provider, preview a quota change, apply it
safely, and verify the result.

This is an operations scenario, not a sandbox-policy change. It does not create
per-user budgets, USD spend caps, or provider billing limits.

## Prerequisites

- Administrator access to the deployed host and its reviewed checkout.
- At least one enabled Praxis provider, such as OpenAI, Anthropic, vLLM, or a
  reviewed custom provider.
- Active model requests stopped before applying a capacity change or resetting
  usage.

Run as the server administrator, separately on each gateway. Use the deployed
checkout path: `/opt/secure-single-server` for manual deployments or
`/usr/share/secure-single-server` on the bootc image.

```console
REPO=/opt/secure-single-server
# On bootc, set REPO=/usr/share/secure-single-server instead.
cd "$REPO"
```

## Check installed limits

```console
sudo scripts/common/quota-status
```

Status shows backend, capacity, reservation and available usage metrics. It also
prints the command for listing adjustable rules. For refresh or JSON:

```console
sudo watch -n 5 ./scripts/common/quota-status
```

```console
sudo scripts/common/quota-status --json
```

> Valkey usage is read directly from its persisted ledger, including after a
> Praxis restart. The separate process counters restart and may show `unknown`.
> Memory quotas reset on restart; refresh after inference for new samples.

## List providers and rules

```console
sudo scripts/common/quota-set --list
sudo scripts/common/quota-set --list --provider vllm
```

The list shows enabled providers, current and minimum capacities, and whether
each rule is settable. It prints a copyable setting command for each selected
rule. Add `--json` for structured output. Listing works without inference metrics.

Disabled providers have no active rules to adjust. Use
[provider operations](#enable-openai-anthropic-or-a-compatible-provider) to
inspect and enable them.

## Enable OpenAI, Anthropic, or a compatible provider

Provider changes preserve other providers and listener authentication, but they
restart Praxis. Finish active tasks first. Valkey quotas persist across the
restart. Run from the matching deployment checkout:

```console
sudo dnf install -y python3-pyyaml
sudo scripts/common/providers show
sudo scripts/common/quota-set --list
```

OpenAI:

```console
sudo scripts/common/providers enable openai
sudo scripts/common/quota-set --provider openai --capacity 2000000
sudo scripts/common/quota-set --provider openai --capacity 2000000 --apply
```

Enter the key at the hidden prompt. It becomes a versioned Podman secret; it is
never passed in command arguments or given to harness users. The quota is an
independent rolling 24-hour token allowance shared by that provider's users.

Anthropic:

```console
sudo scripts/common/providers enable anthropic
sudo scripts/common/quota-set --provider anthropic --capacity 2000000 --apply
```

For another compatible provider, choose a unique lowercase name and replace the
example URL. The upstream must speak the native API used by the harness:
Messages for Claude Code, or the selected SDK API for OpenCode. There is no API
translation.

```console
sudo scripts/common/providers enable team \
  --openai-url https://openai.example.com/v1
sudo scripts/common/quota-set --list --provider team
sudo scripts/common/quota-set --provider team --capacity 2000000 --apply
```

If the same provider and key support native Anthropic Messages, supply both
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
both. Direct OpenAI, Anthropic, and local vLLM budgets remain independent.

## Share the local vLLM quota across harnesses

On a Valkey gateway:

```console
sudo scripts/common/providers enable vllm --shared-quota --capacity 10000000
sudo scripts/common/quota-set --list --provider vllm
sudo scripts/common/quota-status
```

This creates one `vllm-rolling-day` budget for Chat, Responses, and Messages.
It migrates the two existing vLLM ledgers with their original timestamps and
retains charges for interrupted reservations. Old ledgers remain for recovery;
the allowance is the supplied capacity, not the sum of the former capacities.
Migration requires the pinned image and managed 24h/300s Valkey rules.
In-memory quotas cannot share a budget across the two all-in-one listeners.

## Adjust capacities

List and preview the vLLM allowance:

```console
sudo scripts/common/quota-set --list --provider vllm
sudo scripts/common/quota-set --provider vllm --capacity 10000000
```

Stop active tasks before applying: Praxis restarts, interrupting requests and
resetting memory quotas and process metrics. Valkey usage survives; vLLM keeps running.

```console
sudo scripts/common/quota-set --provider vllm --capacity 10000000 --apply
sudo scripts/common/quota-set --list --provider vllm
sudo scripts/common/quota-status
```

For an enabled cloud provider, choose its block. Append `--apply` to save the
previewed capacity, then rerun its list command:

```console
sudo scripts/common/quota-set --list --provider openai
sudo scripts/common/quota-set --provider openai --capacity 2000000
```

```console
sudo scripts/common/quota-set --list --provider anthropic
sudo scripts/common/quota-set --provider anthropic --capacity 2000000
```

To change one rule, use its exact name; `--rule` can be repeated. This example
requires the [shared vLLM quota](#share-the-local-vllm-quota-across-harnesses);
otherwise choose a name printed by `--list`:

```console
sudo scripts/common/quota-set --list --rule vllm-rolling-day
sudo scripts/common/quota-set --rule vllm-rolling-day --capacity 5000000
```

Capacity must cover the reservation shown by the list (`10000` by default).
An unchanged capacity does not restart services. Saved capacities survive
provider changes and same-profile upgrades; other providers' allowances,
credentials, images and quota windows stay unchanged.

## Reset consumed usage for testing

On a managed Valkey gateway, list eligible rules, then preview one provider:

```console
sudo scripts/common/quota-reset --list
sudo scripts/common/quota-reset --provider vllm
```

Stop active tasks before applying. This briefly stops Praxis, clears only the
selected ledgers and outstanding reservations, then restarts it. Capacities,
other providers' usage and the vLLM service are retained.

```console
sudo scripts/common/quota-reset --provider vllm --apply
sudo scripts/common/quota-status
```

Use `--rule NAME` instead of `--provider` to select exact rules; repeat `--rule`
for several. The helper requires the qualified image and managed global Valkey
sliding-window rules. It never flushes the database. Resets cannot be undone.

## Rules, persistence and display limits

| Rule | Shared allowance |
| --- | --- |
| `vllm-rolling-day` | Local Chat, Responses and Messages after [enabling the shared Valkey quota](#share-the-local-vllm-quota-across-harnesses) |
| `vllm-openai-rolling-day`, `vllm-anthropic-rolling-day` | Separate API allowances before migration, or on memory gateways |
| `openai-rolling-day` | Enabled OpenAI routes |
| `anthropic-rolling-day` | Enabled Anthropic routes |
| `NAME-openai-rolling-day`, `NAME-anthropic-rolling-day` | A custom provider’s enabled native APIs |

All users share these allowances. Shipped values are `10000000` tokens per
rolling `24h` on the all-in-one memory shape and `1000000` on the Valkey and
remote-gateway shapes, with a `10000` reservation and a `300s` reservation
timeout. Use the
list for installed values. Input, output and repeated prompt/history tokens count.

| Status / backend | Meaning |
| --- | --- |
| `memory` | Usage is lost on Praxis restart |
| `valkey ledger` | Current persisted window charges plus outstanding reservations, read without changing quotas |
| `first window` | Unchanged global memory balance reconstructed before usage ages out: estimated − refunded + overage |
| `unknown` | Balance cannot be established; check the reported reason |

The Valkey reader supports the pinned Praxis image's global sliding-window rules
and managed local backend. Other images, key scopes and algorithms display
`unknown` until qualified. Charges include estimates retained after missing usage
or reservation expiry; they are not necessarily provider-reported token usage.
The image omits Valkey settlement/refund counters, so cumulative reserved tokens
must not be treated as net charges. Use the first table for the current allowance.
Use the [Valkey profile](../../quickstarts/all-in-one/valkey.md) for restart persistence; changing
from memory starts a new ledger, not a transfer of old usage.

## Read accounting and identify a 429

A token quota denies admission when remaining capacity cannot cover its
reservation. Stop repeated retries, inspect status, then check recent rejections:

```console
sudo bash -c '
  source scripts/common/lib.sh
  as_service podman logs --since 30m --tail 5000 praxis-shared-gateway 2>&1
' | sed -E 's/\x1B\[[0-9;]*[[:alpha:]]//g' \
  | grep -E 'token_rate_limit: rejecting request|request rejected by filter' | tail -n 20
```

`token_rate_limit` names the quota rule; wait for usage to age out or raise its
capacity. `rate_limit` is the separate request throttle (shipped at 2 requests/s,
burst 10). Raising token capacity does not change that throttle. Upstream providers
can also return 429; correlate logs with the request time/path.

## Other settings and gaps

Capacities are stored in managed `/etc/praxis/quota-overrides.json`; do not edit
it by hand. Failed activation restores the previous configuration, with backups
under `/etc/praxis/rollback/quotas-*`. Rollback cannot recover lost memory usage.

Inspect providers, quotas, and the host after any change:

```console
sudo scripts/common/providers show
sudo scripts/common/quota-status
sudo scripts/common/verify --host
```

Repeat `enable NAME` to rotate a key; saved custom URLs are retained. To reuse
an existing Podman secret, add `--secret NAME` instead of entering a new key.
To disable a provider while retaining its secret:

```console
sudo scripts/common/providers disable team
```

Keep at least one provider enabled. Local inference installation is separate;
see [optional vLLM deployment](../../quickstarts/common/vllm.md).

| Setting | Managed location |
| --- | --- |
| Enabled providers, custom URLs, secret references, applied catalog | `/etc/praxis/providers.json` |
| Administrator-edited non-secret model catalog | `/etc/praxis/unified-models.json` |
| Rendered routes, filters and quotas | `/etc/praxis/shared-gateway.yaml` |
| Capacity overrides | `/etc/praxis/quota-overrides.json` |
| Upstream keys | Rootless Podman secrets owned by `praxis-svc` |
| Harness models and menus | User-owned CLI configuration files |

Use the helpers for provider and capacity changes; hand edits to managed files
are rejected as configuration drift. Upgrades retain custom providers, the
shared-vLLM setting, and the applied unified catalog. Failed activation
restores configuration from `/etc/praxis/rollback/`. A failed quota migration
never overwrites a shared ledger; inspect its reported recovery state before
retrying.

For windows, reservations or Switchyard rules, edit source YAML and use the
[all-in-one](../../quickstarts/all-in-one/in-memory.md#operate-the-service) or
[remote-gateway](../../quickstarts/remote-gateway/install.md#operations) upgrade procedure,
retaining its provider/image/security arguments. Saved capacity overrides take
precedence over source capacities.

Quotas are shared token allowances, not per-user, per-model or dollar budgets.
Reservation expiry does not guarantee a refund. Valkey uses AOF `everysec`,
which can lose roughly a second of writes on sudden failure.

## Update the helpers on an existing VM

New deployments include them. For an older deployment, run from the reviewed
workstation checkout with its administrator login and SSH key. The commands
find the checkout root, use `~/.ssh/id_ed25519` unless `SSH_KEY` is already set,
and prompt for the target host in `user@host` form:

```console
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
read -r -p "RHEL host (user@host): " RHEL_HOST
ssh -i "$SSH_KEY" -o IdentitiesOnly=yes -o ForwardAgent=no "$RHEL_HOST" true && \
  scp -p -o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY" \
  scripts/common/quota-status scripts/common/quota_status.py \
  scripts/common/quota-set scripts/common/quota_manage.py scripts/common/quota_config.py \
  scripts/common/quota-reset scripts/common/quota_reset.py scripts/common/unified_config.py \
  scripts/common/providers scripts/common/provider_manage.py scripts/common/provider_config.py \
  scripts/common/quota_share.py \
  scripts/common/lib.sh scripts/common/install \
  "$RHEL_HOST:~/secure-single-server-deploy/scripts/common/"
```

This updates scripts without changing running services. They use Python/PyYAML
and keep the admin listener private.

## Evidence and limits

A successful run shows the selected provider's capacity before and after the
change, confirms the saved value after the Praxis restart, and preserves other
providers' allowances. It does not prove provider billing, exact token
accounting, or suitability for multi-user cost allocation.
