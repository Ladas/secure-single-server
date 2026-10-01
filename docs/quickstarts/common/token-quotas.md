# Token quotas

Run as the server administrator, separately on each gateway.

## Check installed limits

```console
cd ~/secure-single-server-deploy
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

Disabled providers have no active rules to adjust. Inspect their configuration
with `sudo scripts/common/providers show`; enable them using [provider setup](providers.md).

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
requires the [shared vLLM quota](providers.md#share-the-local-vllm-quota-across-harnesses);
otherwise choose a name printed by `--list`:

```console
sudo scripts/common/quota-set --list --rule vllm-rolling-day
sudo scripts/common/quota-set --rule vllm-rolling-day --capacity 5000000
```

Capacity must cover the reservation shown by the list (`10000` by default).
An unchanged capacity does not restart services. Saved capacities survive
provider changes and same-profile upgrades; other providers' allowances,
credentials, images and quota windows stay unchanged.

## Rules, persistence and display limits

| Rule | Shared allowance |
| --- | --- |
| `vllm-rolling-day` | Local Chat, Responses and Messages after [enabling the shared Valkey quota](providers.md#share-the-local-vllm-quota-across-harnesses) |
| `vllm-openai-rolling-day`, `vllm-anthropic-rolling-day` | Separate API allowances before migration, or on memory gateways |
| `openai-rolling-day` | Enabled OpenAI routes |
| `anthropic-rolling-day` | Enabled Anthropic routes |
| `NAME-openai-rolling-day`, `NAME-anthropic-rolling-day` | A custom provider’s enabled native APIs |

All users share these allowances. Shipped values are `1000000` tokens per
rolling `24h`, a `10000` reservation and a `300s` reservation timeout. Use the
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
Use the [Valkey profile](../all-in-one/valkey.md) for restart persistence; changing
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

For windows, reservations or Switchyard rules, edit source YAML and use the
[all-in-one](../all-in-one/in-memory.md#operate-the-service) or
[remote-gateway](../remote-gateway/install.md#operations) upgrade procedure,
retaining its provider/image/security arguments. Saved capacity overrides take
precedence over source capacities.

Quotas are shared token allowances, not per-user, per-model or dollar budgets.
Reservation expiry does not guarantee a refund. Valkey uses AOF `everysec`,
which can lose roughly a second of writes on sudden failure. See
[feature testing](../../testing/gateway-features.md) for qualification.

## Update the helpers on an existing VM

New deployments include them. For an older deployment, run from the reviewed
workstation checkout with its administrator login and SSH key:

```console
scp -p -o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY" \
  scripts/common/quota-status scripts/common/quota_status.py \
  scripts/common/quota-set scripts/common/quota_manage.py scripts/common/quota_config.py \
  scripts/common/provider_manage.py scripts/common/provider_config.py scripts/common/quota_share.py \
  scripts/common/lib.sh scripts/common/install \
  "$RHEL_HOST:~/secure-single-server-deploy/scripts/common/"
```

This updates scripts without changing running services. They use Python/PyYAML
and keep the admin listener private.
