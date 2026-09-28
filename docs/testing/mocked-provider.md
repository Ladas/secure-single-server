# Mocked-provider CI

From the repository root, run the same Praxis checks used by native amd64 and
arm64 CI:

```console
python3 tests/mocked-provider.py --engine podman
```

Use `--engine docker` for Docker. Prerequisites are a running native Linux
container engine, Python 3.9+, OpenSSL, Bash, Ruby/Psych, Git, jq, ripgrep and
ShellCheck 0.11.0. zsh exercises the additional AWS session regressions when
installed. This repository has no workspace-wide build or Makefile gate.
The runner acquires missing digest-pinned images before starting each fixture;
inference uses no public endpoints, provider credentials or AWS access.

For shorter local iterations:

```console
python3 tests/mocked-provider.py --suite offline
python3 tests/mocked-provider.py --suite gateways --engine podman
CONTAINER_ENGINE=podman python3 tests/common/gateway.py --scenario remote --valkey --case quotas
```

The existing `tests/remote-gateway/image.py [--valkey]` entry point runs the
shared remote suite. Existing image startup, native-architecture, Valkey ACL,
persistence, caller-credential, TLS assertion and AWS planning tests remain in
the main runner. The runner returns nonzero on any failure and records each
command's result; a failed profile does not suppress the other profiles.

## Coverage added after PR #4

PR #4 supplies the harness argument/provider/SSH regressions, shared OpenShell
gateway setup tests, HTTP reachability probe regression, bootc build checks,
and a manual disposable-RHEL runtime fixture. This change reuses those checks.

| Area | Existing coverage at PR #4 | Added here |
| --- | --- | --- |
| Gateway requests | Remote memory/Valkey checks using static responses inside Praxis; all-in-one image startup | One observable provider fixture across all four profiles; JSON/SSE, tools, provider counters and controlled failures |
| Quotas and credentials | Remote JSON usage, independent API allowances, TLS/JWT and provider-key checks, Valkey restart/outage checks | Equivalent all-in-one coverage; streaming settlement, first-match checks, missing/partial usage, unchanged provider counts on denial, shared allowance across JWT users and Valkey recovery |
| OpenShell entry points | Six harness/gateway unit tests and the HTTP reachability regression | Seven additional unit tests covering every standalone profile, integrated rendering/rejection, invalid ports and connect failures |
| Policy schemas | Sixteen profiles and a native CLI test that can fail on connection before parsing | Parsing controls shared by native/container runners and a hosted pinned-CLI check for every profile |
| bootc and sandbox runtime | Five bootc unit tests, image/host checks and manual runtime canary/policy scripts | Existing gates preserved; no additional booted-host or sandbox-runtime acceptance |

The main Python count is **33 retained tests plus 11 new fixture/assertion
tests = 44**. OpenShell's **13 unit tests include six retained and seven new**;
the five bootc tests are retained. Matrix scenarios, schema profiles and shell
checks are additional executions, not included in those unit-test counts.
These counts are not a line/branch coverage percentage.

## What these tests prove

| Coverage | All-in-one memory/Valkey | Remote memory/Valkey |
| --- | --- | --- |
| OpenAI Chat Completions and Responses; native Anthropic Messages | Yes | Yes, verified HTTPS and caller JWT |
| JSON and complete SSE, including usage and terminal events | Yes | Yes |
| Scripted `add(2, 3)` tool call and result continuation | Yes | Yes |
| Provider path/model, injected synthetic key, stripped classification headers | Yes | Yes; caller JWT must not reach provider |
| Known usage settles reservations; exhaustion stops provider requests | Yes | Yes |
| Shared OpenAI allowance, independent Anthropic allowance, first-match rule | Yes | Yes |
| Memory reset; Valkey restart persistence, fail-closed outage and recovery | Yes | Yes |
| Changing authenticated users retains the shared allowance | Not applicable | Yes |
| Missing usage, provider 429/500, delayed/truncated streams and client timeout | Yes | Yes |
| Invalid JWT/signature/issuer/audience/expiry, TLS trust/hostname and plaintext | Not applicable | Yes |
| Unknown routes and batch-endpoint bypass regressions | Native passthrough profile | Denied before reaching provider |

With capacity 20 and reservation 10, known usage of two input plus three output
tokens admits exactly three requests. The fourth must return `429` with an
unchanged mock request count. An unselected second catch-all rule with capacity
10 proves that the first matching rule owns the allowance; the test does not
invent an aggregate budget. Chat Completions and Responses share the OpenAI
allowance, while exhaustion leaves the Anthropic allowance usable.
Changing the caller's JWT subject does not create a personal allowance.
After a Valkey outage, admission recovers with the remaining quota intact.

Missing usage and provider errors retain the reservation. The truncated stream
fixture stops after its first event: OpenAI has not reported usage at that
point, while Anthropic has reported two input tokens. The pinned image settles
that partial Anthropic usage. This is a regression test of current behavior,
not a guarantee of full accounting for every interrupted upstream response.
Client timeout tests cancel before headers arrive and verify that outstanding
reservations still block admission. Long-running requests, reservation expiry
and production provider-specific interruption behavior need separate qualification.

The client reads each response to completion before asserting its SSE events.
This verifies stream contents and accounting, but does not detect a proxy that
buffers the entire stream. Prompt event delivery, client disconnection during
an active stream, concurrent admission and reservation expiry are not tested.

## Fixtures and permitted substitutions

`tests/common/provider.py` uses Python's standard library and can also be
imported by a later VM smoke runner. Its reusable functions provide complete
JSON/SSE fixtures, a deterministic tool exchange and controlled error modes.
`tests/common/gateway.py` runs the actual scenario configuration and unchanged
authentication, policy, routing, credential and accounting filter chains.

Only the following inputs are substituted:

- Provider destinations and upstream TLS/authority become loopback mocks;
  private endpoints are enabled for these fixtures.
- TLS certificates, signing keys and provider/Valkey credentials are synthetic.
- Models, quota capacities and reservation sizes are deterministic test inputs.
  The first-match case adds an unselected catch-all rule. Per-case Valkey
  namespaces stay within the shipped ACL's permitted prefix.
- Bind mounts, container/network/volume names and published ports are test-owned.

The provider and Praxis share a network namespace. Inference mocks bind only
its loopback interface; provider ports are not published. Gateway and mock
control ports use random host-loopback mappings. Valkey stays on the test-owned
bridge and has no published port. The bridge permits image-engine networking;
the tests themselves make no external inference calls. The control listener
must never be included in a sandbox allowlist.

The control API provides `/state` and `/scenario`. Records contain path, model,
protocol mode and boolean credential/classification checks, never raw headers
or caller tokens. Request counters include rejected and unsupported provider
requests, so an upstream `404` or `429` cannot imitate a gateway denial.

## OpenShell harness and schema contracts

Run the OpenShell contracts separately on Linux with Bash 4.4+, Python/PyYAML,
Node.js 18+ (with `fetch`) and a running container engine:

```console
python3 tests/mocked-provider.py --suite openshell --engine podman
```

The offline tests execute the real create/connect entry points with fake
CLI/SSH commands. They cover all three standalone harnesses and four profiles,
invalid arguments, integrated OpenCode port/model rendering and rejection of
integrated Codex/OpenClaw configuration. They reuse the merged regressions for
explicit provider bindings, readiness, gateway setup and SSH credential
isolation. The denial-probe regression runs a real local HTTP server: HTTP
200, 401, 403 and 500 all establish reachability and cannot prove a network denial.

The schema test uses the exact pinned OpenShell CLI with networking disabled.
Native and container runners share valid/invalid controls before checking all
16 standalone and rendered integrated profiles. `policy set` parses the policy
before connecting; `sandbox create` can fail on connectivity before parsing.
A gateway connection failure alone never establishes that a policy was parsed.
These checks now exercise the fixes merged in PR #4 and must pass, without
expected-failure markers. macOS's bundled Bash 3.2 is insufficient; use a Linux
test environment for the harness entry points.

Sandbox runtime, positive sandbox → Praxis → mock inference, credential-canary
isolation and actual policy-denial evidence are **not run** by this change.
The merged OpenShell runtime workflow requires manual dispatch,
`OPENSHELL_SELF_HOSTED=true`, and a disposable RHEL 9 x86_64 runner labeled
`self-hosted/Linux/X64/rhel9/openshell-disposable`. A skipped runtime job is not
evidence of coverage. The existing integration matrix still limits integrated
Praxis support to experimental OpenCode; schema acceptance does not qualify
the review profile for CLI execution or any profile for useful coding tasks.
PR #4's [validation record](../../bootc/VALIDATION.md) reports failed network
positive controls and unresolved integrated routing. Its runtime canary and
policy scripts exist; this hosted suite does not rerun or replace that qualification.

## Roadmap coverage

The [current roadmap](../roadmap.md) governs the acceptance boundary:

| Roadmap outcome | Covered here | Remaining acceptance |
| --- | --- | --- |
| Phase 1: shared gateway and durable quotas | Three scripted APIs, JSON/SSE/tools, first-match catch-all rules, credential injection, private Valkey restart/outage/recovery | Ordered model-specific deployment rules, native RHEL account/systemd/SELinux behavior and real harness tasks; memory remains development-only |
| Phase 5: individual access and quotas | Remote TLS/JWT rejection and shared allowances across caller identities | Personal/model/team limits together, IdP integration, renewal and revocation |
| Phase 6: retained sandboxed work | Create/connect/configuration contracts, schema parsing, HTTP denial-probe regression | Positive sandbox inference, credential canaries, enforced network/filesystem boundaries, retained processes, reconnect/reboot, collaboration and resource/storage limits |
| bootc deployment | Existing build-contract and ShellCheck CI checks are preserved | Native image builds and booted-host qualification; memory-backed bootc does not provide durable quotas |

Routing/failover and judge accounting (phase 2), guardrails (phase 3), managed
vLLM (phase 4), external usage export (phase 7), and monetary budgets remain
outside this suite. Scripted tool exchanges do not qualify an actual coding
harness. Token reservations do not provide billing or hierarchical quotas.

## Evidence and scope

Results are written under ignored `evidence/mocked-provider/`, including a
failed status when a command fails and bounded, redacted gateway logs on test
failure. CI uploads only these JSON files, retained for seven days. Generated
keys, mounted configurations and raw container inspection output are excluded.
Cleanup removes only the randomly named resources owned by each fixture;
there is no engine-wide prune or shared-host service installation.

Passing this suite proves protocol/configuration contracts against scripted
providers. It does not prove real-model coding ability, actual harness tool
tasks, RHEL systemd/SELinux/account separation, logout/reboot survival or AWS
networking. Continue with [RHEL VM qualification](rhel-vm.md),
[AWS testing](aws.md) and [real-provider harness acceptance](harnesses.md).
