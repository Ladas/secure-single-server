# Gateway feature testing

Use this checklist for token quotas, persistence and harness recovery. Keep
per-harness tool/menu results in the [compatibility matrix](compatibility.md);
its [feature summary](compatibility.md#gateway-feature-qualification) links here.
Normal manual inference can begin before this qualification is complete.

## Run the existing accounting tests

From the repository root with Podman running:

```console
python3 tests/mocked-provider.py --suite gateways --engine podman
```

Use `--engine docker` for Docker. This runs both roles with memory and Valkey,
using the pinned Praxis image and synthetic providers. It changes no installed
VM services. Prerequisites and evidence are in the
[mocked-provider guide](mocked-provider.md).

For one focused quota regression:

```console
CONTAINER_ENGINE=podman python3 tests/common/gateway.py \
  --scenario remote --valkey --case quotas
```

This lower-level runner calls the remote-gateway scenario `remote`. Use
`--scenario all-in-one` for the local role, omit `--valkey` for memory, or use
`--case failures` for interrupted/error responses. JSON results go under
`evidence/mocked-provider/`.

**Already covered:** Chat/Responses/Messages JSON and complete SSE settlement;
quota exhaustion with no upstream request; first-match rules; shared
Chat/Responses allowance and independent Anthropic allowance; shared allowance
across remote JWT subjects; memory reset; Valkey restart, outage and recovery.
Missing usage, upstream 429/500, delayed/truncated SSE and timeout before headers
also have regressions. These are container contracts, not native harness or
RHEL persistence results. Streaming contents are checked after completion;
prompt delivery of stream events is not established.

## Small limits for a disposable mock test

The [administration guide](../quickstarts/common/token-quotas.md) defines the
production settings. For a fast, deterministic API test, the proposed lab
settings are:

| Setting | Lab value | Purpose |
| --- | --- | --- |
| `capacity` | `20` | Small allowance, with no paid token consumption |
| `reserved_tokens` | `10` | Two outstanding reservations fill the allowance |
| `window` | `60s` | Observe recovery without a daily wait |
| `reservation_timeout` | `30s` | Exercise expiry with a controlled delayed mock |
| Mock terminal usage | 2 input + 3 output | Five tokens charged per completed request |

With sequential requests completing before expiry, **three requests must pass
and the fourth must return 429**: the remaining five tokens cannot admit a
reservation of ten. Missing usage instead leaves the reservation charged;
two such requests exhaust admission. Do not use these settings for real Qwen.
Keep ordinary settlement tests below 30 seconds; test expiry separately.
Use a longer window if a native mock task cannot finish within 60 seconds.

There is **no RHEL quota-test flag yet**. The container suite already overrides
capacity/reservation; the short-window RHEL profile and automatic restoration
remain unimplemented.
Until implemented, use a disposable mock VM and the supported administrator
workflow: edit the selected source gateway YAML in a separate reviewed bundle,
transfer it, and apply a same-profile managed upgrade with the existing provider,
TLS/JWT and secret arguments. See [all-in-one operations](../quickstarts/all-in-one/in-memory.md#operate-the-service)
or [remote operations](../quickstarts/remote-gateway/install.md#operations).
Restore the original bundle through the same workflow and verify it afterward.
Do not edit live files behind the install manifest or reset unrelated Valkey keys.

## Remaining acceptance

Every row below is **Not run on RHEL** as a feature qualification. Run mock
cases for both gateway roles and both quota backends. Run harness cases with
Codex, Claude Code and OpenCode on their supported native API routes; add
OpenShell rows as adapters become available. Real long-request checks need
separate CPU/GPU evidence.

| ID | Test | Required observation |
| --- | --- | --- |
| Q1 | Exhaustion and settlement | Repeat the 3-pass/4th-denied test for JSON/SSE on every enabled API; gateway denial leaves the provider request count unchanged |
| Q2 | Harness quota errors | Exhaust before the first prompt, then between a tool call and continuation; record CLI error, retry count/delay, cancellation and recovery after the window. No false success or duplicated tool execution |
| Q3 | Shared and independent allowances | Two OS users / two JWT subjects share the same rule. Chat and Responses share; Anthropic is independent. Rendered local-vLLM quotas remain separate from cloud quotas |
| Q4 | Concurrent admission and expiry | Hold two reserved requests open; reject a third. Exercise completion before and after reservation expiry, and reported usage above the estimate; detect early readmission or double settlement |
| Q5 | Real CPU/GPU request lifetime | Measure individual request duration and usage, including thinking, against the configured reservation timeout; test a request longer than the timeout and then a competing admission |
| Q6 | Streaming interruption | Observe events before completion; disconnect during an active stream. Compare complete, partial and missing terminal usage with the amount charged and subsequent admission |
| Q7 | Window recovery | Recover without restart after usage ages out; test a rolling-window boundary. Record actual recovery time, not a presumed calendar reset |
| Q8 | RHEL restart and Valkey failure | Exhaust, restart Praxis, then reboot the host: memory resets; Valkey retains the allowance. Stop Valkey: fail closed without forwarding; restore it: remaining allowance survives |
| Q9 | Discovery and non-inference routes | Check model listing and token counting separately from inference. Verify whether they consume reservations; menu use must not silently drain inference allowance |
| Q10 | Authentication and upstream errors | Invalid/expired JWTs must not forward or spend quota. Distinguish gateway 429, request-rate 429 and upstream 429/500 using provider records and gateway evidence |

For Q2, start with mocks and ordinary users. Repeat real-provider error behavior
only after deterministic cases pass. Record `Retry-After` if present; do not
assume it exists or every CLI handles it. Test the same prompt after recovery
without resetting counters or changing credentials.

For Q4/Q5, the mutable gateway templates use a **300s reservation timeout**;
the separate bootc vLLM config uses 1800s. A CPU tool task taking 6–11 minutes
does not prove a timeout bug: it contains multiple requests. Measure each
request. Reservations are estimates, not maximum output or dollar budgets.
Do not simply increase the timeout and call expiry semantics qualified.

For Q6, current interrupted Anthropic fixtures settle the partial input usage
already reported; OpenAI fixtures without usage keep the reservation. Neither
proves accurate accounting for an interrupted real provider.

For Q9, the baseline all-in-one configuration applies its quota filter to model
listing too. Optional-provider rendering adds method/path conditions. Qualify
the actual installed configuration rather than generalizing from one profile.
For quota-focused cases, pace requests below the request-rate limit so an
unrelated 429 cannot look like correct token accounting.

## Record and restore

Save scenario, host/client location, user type, image/configuration hashes,
provider/API, memory/Valkey, quota values, request durations, returned status,
reported usage, provider request counts and CLI retries. Keep tokens and raw
credentials out of evidence. A service health check alone does not prove
counter persistence; compare admissions before and after the restart.

After experiments, restore the reviewed normal configuration, remove owned
fixtures and verify a normal tool task. Return CPU/GPU hosts to real Qwen with
no mocks before manual use. Store detailed private results with the other
RHEL evidence and update only the matching feature-summary cells. Usage export
is tracked by [#21](https://github.com/redhat-et/secure-single-server/issues/21).
