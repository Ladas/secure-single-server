# Token quotas

A token quota is an allowance over a usage window. These profiles use the
`token_rate_limit` filter for **rolling daily quotas**, not just short bursts.
Request throttling (`rate_limit`) is separate.

| Setting | Shipped value | Meaning |
| --- | --- | --- |
| Algorithm | `sliding_window` | Usage in the previous window consumes capacity |
| `window` | `24h` | Rolling day; use `168h` for a rolling week |
| `capacity` | `1000000` | One million total tokens per provider/API quota |
| `reserved_tokens` | `10000` | Admission reserves this estimate per request |
| `reservation_timeout` | `300s` | Reservation lifetime; qualify long-running requests |
| Accounting | Reported input + output | Actual usage settles the reservation when available |
| Backend | Valkey for persistent deployment | Memory resets quota state on Praxis restart |

There are **two independent allowances**: OpenAI and Anthropic. All callers
share them, including authenticated JWT callers. The OpenAI allowance covers
Responses and Chat Completions together; it is not one allowance per harness.
An insufficient allowance rejects admission with `429`.

## Administrator configuration

Before installation, edit the scenario's supplied gateway YAML in the reviewed
workstation checkout. Change the named quota's window, capacity and reservation
together; reserve no more than the capacity. Transfer the reviewed bundle again
and use the documented same-profile upgrade workflow. Do not edit live managed
files behind the installer's manifest.

For a small **disposable** quota-exhaustion test, use capacity `20`, reservation
`10`, and a short rolling window. Do not consume a million paid tokens merely
to test denial. Validate settlement as well as admission: reservations are
estimates, not hard maximum-output caps.

## Persistence and gaps

| Topic | Current behavior / gap |
| --- | --- |
| Restart | Private Valkey retains quota state. AOF `everysec` can lose roughly the last second of writes on sudden failure; this is not zero-loss durability. Test outage/recovery and fail-closed behavior before acceptance. |
| Per-model rules | These quickstarts ship catch-all provider/API quotas. Ordered model-specific rules need trusted model classification and qualification. First-match rules are independent; a model rule does not also charge a catch-all. |
| Per-user quotas | A JWT authenticates its bearer; it does not add per-user counters to these configurations. |
| Token types | Input/output are combined; no separate input, output or cached-token allowance is configured. Verify each API's usage reporting. |
| Missing usage | The estimate can remain charged; do not assume a refund. Cancellation, streaming and long requests need accounting tests. |
| Batch APIs | Remote gateway blocks batch endpoints. A batch-creation response is not final inference usage; admitting asynchronous jobs needs separate reservation and settlement support. |
| Calendar resets | Rolling `24h`/`168h` does not reset at midnight/Monday. |
| Price | Different models and token types have different prices. Token quotas are not dollar budgets; USD enforcement is later work. |
| Routing | Switchyard's current profile has one separate catch-all quota; selected-model quotas and judge accounting remain gaps. |

Valkey is one standalone container, not Valkey plus Redis. It persists token
quota data only: request-rate buckets and Switchyard decisions remain in memory.
