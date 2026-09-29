# Compatibility and test matrix

Every acceptance path below includes Praxis. **Direct** means the harness runs
under an ordinary OS account, outside OpenShell. **Bypass** means a diagnostic
request to vLLM without Praxis; it is never an acceptance result.

- **Passed**: native CLI streaming, a tool task and tool-result continuation
  passed. Real Qwen smoke also requires generated files and independent unittest
  checks. This is functional smoke coverage, not general coding reliability.
- **Failed**: the test ran and failed; the command returns nonzero.
- **Not run**: no runtime result for that exact combination.
- **Blocked**: required access, launcher, sandbox image or provider adapter is missing.

Start qualification with **OpenCode → Praxis → Qwen**. Real cloud calls
remain untested; passing mocks do not qualify real OpenAI/Anthropic accounts.

## All-in-one

Both variants run Praxis and their selected CPU/GPU vLLM on the same host.
OpenShell is a separate execution mode on that host after the direct baseline.
**CPU remote-gateway results do not populate CPU all-in-one cells.**

### Direct harnesses as ordinary users

#### Qwen3-8B / vLLM 0.30

| Harness | Mock model | Real CPU | Real GPU |
| --- | --- | --- | --- |
| Codex | Passed | Passed | Passed |
| Claude Code | Passed | Passed | Passed |
| OpenCode | Passed | Passed | Passed |

Real results use the current Praxis PR #40 image and thinking enabled: all
three native CLIs and all six JSON/SSE API checks passed on CPU and GPU.
Mock results cover both hosts with the previous Praxis image; they do not use
CPU/GPU inference. Current-image container provider tests also pass; native
mocked CLI tasks have not been repeated after the image upgrade.
A stricter Responses capture found streamed/final tool-ID drift despite the
Codex pass; see [backend diagnostics](#backend-diagnostics-and-fix-ownership).

#### OpenAI models

| Harness | Mock provider | Real OpenAI model |
| --- | --- | --- |
| Codex | Passed | Not run |
| OpenCode | Passed | Not run |

#### Anthropic models

| Harness | Mock provider | Real Anthropic model |
| --- | --- | --- |
| Claude Code | Passed | Not run |
| OpenCode | Passed | Not run |

Cloud mock results cover both hosts. No real cloud model is qualified yet;
choose an account-approved model ID for each real run. Cloud inference has no
local CPU/GPU distinction. Codex uses Responses; OpenCode uses Chat Completions
or Anthropic Messages; Claude uses Messages. Routes forward the native API
without translation. Codex → Anthropic and Claude → OpenAI are not configured.
OpenClaw is included only in the OpenShell tables.

### OpenShell harnesses for ordinary users on the same host

These are **mutable AWS RHEL** results. Direct-host tests, recipe rendering and
a Ready sandbox do not qualify a sandbox CLI task. The merged TLS/mTLS change
requires operator credentials; personal-user enrollment is still missing.

#### Qwen3-8B / vLLM 0.30

| Harness | Mock model | Real CPU | Real GPU |
| --- | --- | --- | --- |
| Codex | Blocked [1] | Blocked [1] | Blocked [1] |
| Claude Code | Blocked [2] | Blocked [2] | Blocked [2] |
| OpenCode | Blocked [4] | Blocked [4] | Blocked [4] |
| OpenClaw | Blocked [3] | Blocked [3] | Blocked [3] |

1. Codex's sandbox recipe lacks a Praxis adapter and rejects `--config`.
2. Claude needs a pinned sandbox image and recipe.
3. OpenClaw's sandbox recipe lacks a Praxis adapter and rejects `--config`.
4. [#12](https://github.com/redhat-et/secure-single-server/issues/12): ordinary-user
   enrollment/workspace access is missing. All sandbox rows also need this
   access; service-operator tests are recorded separately below.

#### OpenAI models

| Harness | Mock provider | Real OpenAI model |
| --- | --- | --- |
| Codex | Blocked [1] | Blocked [1] |
| OpenCode | Blocked [3] | Blocked [3] |
| OpenClaw | Blocked [2] | Blocked [2] |

1. Codex's sandbox recipe lacks a Praxis adapter.
2. OpenClaw's sandbox recipe lacks a Praxis adapter.
3. [#12](https://github.com/redhat-et/secure-single-server/issues/12): ordinary-user
   enrollment/workspace access is missing for these sandbox clients.

#### Anthropic models

| Harness | Mock provider | Real Anthropic model |
| --- | --- | --- |
| Claude Code | Blocked [1] | Blocked [1] |
| OpenCode | Blocked [2] | Blocked [2] |
| OpenClaw | Blocked [3] | Blocked [3] |

1. Claude needs a pinned sandbox image and recipe.
2. OpenCode's sandbox recipe lacks an Anthropic Messages adapter.
3. OpenClaw's sandbox recipe lacks a Praxis/Anthropic adapter. All rows also
   require individual enrollment tracked in [#12](https://github.com/redhat-et/secure-single-server/issues/12).

OpenCode's Qwen/OpenAI rendering passes offline checks. The Qwen route is
`/vllm/v1`; the OpenAI route is `/v1`. The runner's optional `--phase openshell`
checks an API request and policy denial, not a native CLI file/test task.
Use [sandbox acceptance](openshell-manual.md) to qualify the cells above.

### OpenShell service-operator checks

These use the locked `openshell-svc` management identity; harness processes run
as the sandbox user. They do not qualify ordinary-user access blocked by #12.

| Check | CPU | GPU |
| --- | --- | --- |
| Addon install, authenticated management, sandbox create/SSH | Passed | Passed |
| Management TLS rejects missing client certificate | Passed | Passed |
| Gateway telemetry disabled | Passed | Passed |
| Praxis model-list API from sandbox | Not run | Passed |
| Streaming Qwen answer from sandbox | Not run | Passed |
| Nonstreaming Qwen answer from sandbox | Failed [1] | Failed [1] |
| OpenCode native file/test task | Failed: generated tests fail [4] | Passed [2] |
| Controlled network positive control | Passed | Passed |
| Controlled denial proof | Failed: inconclusive [3] | Failed: inconclusive [3] |
| Effective sandbox limits | Not run | Passed: 2 CPU / 4 GiB |

1. Nonstreaming POST closes before a response; GPU streaming succeeds through
   the same route. An identical GPU request from the host returns HTTP 200.
   This points to the sandbox transport path; the exact cause is unconfirmed
   and no focused issue has been filed.
2. OpenCode 1.18.31 generated `add.mjs` and three Node tests, ran them through a
   tool, continued to a final answer, and passed independent execution. The
   image has no Python, so the direct-host Python task cannot run unchanged.
3. The allowed request reaches the controlled server and returns its expected
   401. The denied case returns `ENOTFOUND`, not the required explicit denial.
   It remains a failed qualification, not proof of confinement. See #23/#24 below.
4. CPU OpenCode creates files but its generated Node tests fail independently.
   The CLI returning zero does not make this a pass. This differs from the
   passing direct-host Python task and does not establish a transport defect.

### Model listing and model selectors

**API listing**, **a visible menu entry**, and **inference after selection** are
separate checks. Praxis forwards provider-specific model routes; this setup has
no aggregated Qwen/OpenAI/Anthropic model catalog. The launcher configures one
provider/model for each invocation. Direct `/vllm/v1/models` API listing passes
on both CPU and GPU; the sandbox API results are recorded above.

| Harness / selector | Direct CPU | Direct GPU | OpenShell CPU | OpenShell GPU |
| --- | --- | --- | --- | --- |
| Codex `/model` | Failed: Qwen absent [1] | Failed: Qwen absent [1] | Blocked [4] | Blocked [4] |
| Claude Code `/model` | Passed: configured Qwen [2] | Passed: configured Qwen [2] | Blocked [4] | Blocked [4] |
| OpenCode `/models` | Passed: configured Qwen [3] | Passed: configured Qwen [3] | Catalog only [3] | Catalog only [3] |
| OpenClaw selector | — | — | Blocked [4] | Blocked [4] |

1. The pinned Codex menu lists its built-in OpenAI catalog. `--model qwen3-8b`
   still works through Praxis, as the native tasks above demonstrate. A custom
   model-catalog integration is needed; `/v1/models` success does not fix this.
2. Claude shows Qwen through the configured model aliases, not a fetched Praxis
   catalog. Other built-in choices remain visible and are not qualified.
3. OpenCode lists the model configured by the launcher/recipe. Direct menus and
   `opencode models praxis` were checked. CPU/GPU sandbox catalog output lists Qwen;
   interactive sandbox menu checks remain inconclusive. This is not automatic discovery.
4. Missing sandbox adapters/image and ordinary-user access are listed above.

#### OpenAI model selectors

| Harness | Direct selector | OpenShell selector |
| --- | --- | --- |
| Codex | Not run for an approved cloud model | Blocked [1] |
| OpenCode | Not run | Not run for operator; personal access blocked [2] |
| OpenClaw | — | Blocked [1] |

1. Praxis adapters and individual access are missing.
2. Individual enrollment is missing (#12).

#### Anthropic model selectors

| Harness | Direct selector | OpenShell selector |
| --- | --- | --- |
| Claude Code | Not run | Blocked [1] |
| OpenCode | Not run | Blocked [2] |
| OpenClaw | — | Blocked [2] |

1. Sandbox image, recipe and individual access are missing.
2. Anthropic/Praxis adapters and individual access are missing.

These cloud checks have no CPU/GPU distinction. Mock inference passes above do
not qualify model selectors. Selecting a displayed entry and completing a new
request is still a separate acceptance step; current native tasks launch the
model explicitly. See [repeatable selector checks](harnesses.md#model-selector-checks).

## Remote-gateway

The gateway serves HTTPS/JWT. Recorded **CPU gateway VM** results use vLLM 0.19
with thinking disabled. Neither remote-gateway variant has been qualified
with the current vLLM 0.30/thinking-enabled defaults.
Harnesses normally run on separate client machines. Existing automation runs
ordinary-user CLIs on the gateway VM against loopback HTTPS/JWT and separately
probes public TLS/JWT from the workstation. This qualifies the installed CPU
backend/native API path, not a full external-client CLI session.

### Direct harnesses on the gateway VM

#### Qwen3-8B / vLLM 0.19 baseline

| Harness | Mock model | Real CPU | Real GPU |
| --- | --- | --- | --- |
| Codex | Passed | Failed: tool stream | Not run |
| Claude Code | Passed | Failed: system role | Not run |
| OpenCode | Passed | Passed | Not run |

These mocks ran on the CPU gateway VM; they do not exercise inference hardware.
Real results use the older, thinking-disabled backend. **vLLM 0.30 with thinking
is Not run on both remote-gateway variants.**

#### OpenAI models

| Harness | Mock provider | Real OpenAI model |
| --- | --- | --- |
| Codex | Passed | Not run |
| OpenCode | Passed | Not run |

#### Anthropic models

| Harness | Mock provider | Real Anthropic model |
| --- | --- | --- |
| Claude Code | Passed | Not run |
| OpenCode | Passed | Not run |

Cloud mocks ran on the CPU gateway VM through loopback HTTPS/JWT. No real cloud
model is qualified. Public TLS/JWT API probes passed separately: valid callers
were accepted and invalid callers rejected.

### External clients: direct and OpenShell

Harnesses run on a separate client host against the public gateway URL. These
are full CLI tasks; the earlier public API probes cannot populate these cells.
OpenShell belongs on that client host, not on the remote-gateway VM.

#### Qwen3-8B / current vLLM 0.30 target

| Harness | Execution | Mock model | Real CPU gateway | Real GPU gateway |
| --- | --- | --- | --- | --- |
| Codex | Direct | Not run | Not run | Not run |
| Codex | OpenShell | Blocked [1] | Blocked [1] | Blocked [1] |
| Claude Code | Direct | Not run | Not run | Not run |
| Claude Code | OpenShell | Blocked [1] | Blocked [1] | Blocked [1] |
| OpenCode | Direct | Not run | Not run | Not run |
| OpenCode | OpenShell | Blocked [1] | Blocked [1] | Blocked [1] |
| OpenClaw | OpenShell | Blocked [1] | Blocked [1] | Blocked [1] |

1. Remote OpenShell recipes need HTTPS/CA/JWT adapters and gateway egress
   policy, in addition to the harness-specific gaps listed under all-in-one.

#### OpenAI models

| Harness | Execution | Mock provider | Real OpenAI model |
| --- | --- | --- | --- |
| Codex | Direct | Not run | Not run |
| Codex | OpenShell | Blocked [1] | Blocked [1] |
| OpenCode | Direct | Not run | Not run |
| OpenCode | OpenShell | Blocked [1] | Blocked [1] |
| OpenClaw | OpenShell | Blocked [1] | Blocked [1] |

1. Remote OpenShell recipes need HTTPS/CA/JWT adapters and gateway egress
   policy; Codex and OpenClaw also lack their Praxis adapters.

#### Anthropic models

| Harness | Execution | Mock provider | Real Anthropic model |
| --- | --- | --- | --- |
| Claude Code | Direct | Not run | Not run |
| Claude Code | OpenShell | Blocked [1] | Blocked [1] |
| OpenCode | Direct | Not run | Not run |
| OpenCode | OpenShell | Blocked [1] | Blocked [1] |
| OpenClaw | OpenShell | Blocked [1] | Blocked [1] |

1. Remote OpenShell recipes need HTTPS/CA/JWT adapters, gateway egress policy
   and each harness's Anthropic integration; Claude also needs its image/recipe.

Remote model selectors are **Not run**, for both CPU/GPU gateways and all cloud
providers. Earlier authenticated model-list API probes do not establish client
menu behavior. Use the [remote CLI acceptance commands](harnesses.md#remote-gateway-client).

## OpenShell blockers and open issues

| Issue | What it blocks | Does it prevent an operator's basic inference test? |
| --- | --- | --- |
| [#12: identity/workspaces](https://github.com/redhat-et/secure-single-server/issues/12) | Ordinary-user login, private workspaces, user separation and per-user quotas | No; the authenticated service operator can run a separate test, but it does not qualify personal access |
| [#13: provider profiles](https://github.com/redhat-et/secure-single-server/issues/13) | Managed provider attachment/detachment and credential lifecycle | No; the existing OpenCode config recipe can be tested; missing Codex/OpenClaw/Anthropic adapters remain separate implementation gaps |
| [#14: Praxis endpoint rules/TLS](https://github.com/redhat-et/secure-single-server/issues/14) | Claiming method/path-level confinement and TLS on the sandbox-to-Praxis hop | No; test inference and network-denial controls separately |
| [#17: stop/start/reconnect](https://github.com/redhat-et/secure-single-server/issues/17) | Retained task/workspace and reboot-survival qualification | No |
| [#18: managed exec](https://github.com/redhat-et/secure-single-server/issues/18), [#23: structured evidence](https://github.com/redhat-et/secure-single-server/issues/23) | Reliable automation independent of login-shell output and human log formatting | Not inherently; record any concrete execution failure instead of treating every probe failure as a policy denial |
| [#20: GPU sandbox CDI](https://github.com/redhat-et/secure-single-server/issues/20) | Tools that request a GPU inside the sandbox | No; a CPU sandbox calling GPU vLLM through Praxis does not require GPU passthrough |

[#24](https://github.com/redhat-et/secure-single-server/issues/24) tracks policy
proofs. It and [#23](https://github.com/redhat-et/secure-single-server/issues/23)
are relevant to the inconclusive denial test above, but neither is a confirmed
explanation for the nonstreaming transport failure. No open issue yet precisely
tracks that failure or the missing harness adapters. Provenance, attestations,
release tracking, templates and audit-export work do not by themselves block
basic inference.

Merged [#28](https://github.com/redhat-et/secure-single-server/pull/28) disables
telemetry, [#31](https://github.com/redhat-et/secure-single-server/pull/31) adds
management TLS/mTLS, and [#33](https://github.com/redhat-et/secure-single-server/pull/33)
corrects inference migration guidance. Their merge does not supply the missing
harness adapters or personal-user enrollment.

## External-provider-only VMs

The `all-in-one-cloud` and `remote-gateway-cloud` AWS presets install no local
vLLM. Fresh runtime qualification of those deployments is **Not run**, for both
direct and OpenShell clients. Earlier OpenAI/Anthropic mock passes above verify
the provider routes on the recorded hosts; real cloud accounts remain untested.

## Thinking mode

Mutable RHEL installs enable **Qwen thinking**. The all-in-one tables above
qualify this setting. Remote-gateway and bootc results remain a separate
**thinking disabled** baseline; their thinking-enabled qualification is pending.
Mocks do not exercise model reasoning.

The target is usable reasoning, final answers and tools in each harness's
native API. It does not imply identical answers, context capacity or model
quality across Qwen, OpenAI and Anthropic. OpenCode explicitly enables
reasoning and preserves its separate field across tool turns; Codex and
Claude use limits for the installed 16k context. A GPU OpenCode run emitted
separate reasoning, text and tool events and passed the independent file tests.
The basic API checks require final answer text, completion and token usage;
reasoning alone cannot satisfy them.

## Versions and deployments

The mutable AWS results use RHEL 9.8 x86_64, Podman 5.8.2, enforcing SELinux and
memory quotas. GPU all-in-one uses `g6.2xlarge` (NVIDIA L4); CPU all-in-one
and the recorded CPU remote-gateway use `m7i.4xlarge`. GPU remote-gateway
has no results yet. [Deploy variants independently](aws.md#3-deploy-the-vms-you-need).

The current Praxis pin is the published PR #40 image:
`quay.io/opendatahub/praxis-experimental@sha256:227d421e963c477038a884dc51ec880c5d0afa30098ae31028ecf85e963e40d5`,
source `019aa849a219e5c881d69e4a40a1fc190bd6c404`. Native forwarding is enabled;
API translation is untested. Earlier results used Praxis digest
`sha256:a3006352106c2264427faa79b57cf7b49287f3f9bfffe9b2eef869d3429988e8`.

Mutable RHEL vLLM is pinned to 0.30.0 with Qwen3-8B; CPU/GPU have
[separate image digests](../../configs/vllm/images.env). Direct harness pins are
Codex 0.157.1, OpenCode 1.18.32 and Claude Code 2.1.283
([version file](../../configs/common/harness-versions.json)). Keep results for a new
image, API translation mode, CLI pin or deployment separate from this baseline.

## CPU/GPU limits and measured performance

These are Qwen3-8B lab settings, with thinking enabled on both backends. The
launcher configures context limits explicitly; cloud-model defaults do not
apply to this smaller backend.

| Setting or observation | All-in-one CPU | All-in-one GPU |
| --- | --- | --- |
| AWS host | `m7i.4xlarge`, 16 vCPU / 64 GiB | `g6.2xlarge`, NVIDIA L4 / 32 GiB |
| Model precision / server context | BF16 / 16,384 tokens | BF16 / 16,384 tokens |
| Concurrent inference requests | 1; additional requests queue | 1; additional requests queue |
| OpenCode / Claude output budget | 4096 tokens, including thinking | 4096 tokens, including thinking |
| Codex context / auto-compaction threshold | 16,384 / 12,288 tokens | 16,384 / 12,288 tokens |
| Codex output budget | Remaining server context; pinned CLI exposes no separate output-cap setting | Same |
| Automated real CLI deadline | 60 minutes per harness | 30 minutes per harness |
| Observed vLLM 0.30 generation rate | About 3 tokens/s | About 15 tokens/s |
| Approximate time to generate the full 4096-token budget at that rate | 23 minutes, before other overhead | 4.5 minutes, before other overhead |
| Current-image OpenCode file/test task | 6.4 minutes | 1.5 minutes |
| Current-image Claude file/test task | 11.0 minutes | 2.2 minutes |
| Current-image Codex file/test task | 9.1 minutes | 1.9 minutes |
| Consequence for manual use | Expect minutes per tool task; prefer GPU for interactive work | Faster, but still limited by this model and context size |

Rates are observed single-request server samples, not sustained benchmarks or
latency guarantees. They exclude prompt processing, tool execution and queueing.
Durations are complete native runs of the same task, one sample per backend
and harness. Reasoning length and model decisions vary, so these are not pure
hardware comparisons. Both OpenCode runs used the final launcher and passed
file creation, native unittest execution and independent checks.
Earlier CPU Codex runs looped or timed out; the current-image run passed.
Model decisions vary, so this single pass does not establish that Praxis caused
or fixed the earlier task failures.

The runner detects CPU/GPU from the installed backend and records its deadline, client
limits, API-check duration and each harness's elapsed time in result JSON.
Timeouts remain failures, and thinking is never disabled to meet a deadline.
Mocks retain a three-minute deadline per harness.

## Historical comparisons

### All-in-one: vLLM 0.19

The previous Praxis image and the same model with thinking enabled produced these results:

| Harness | Real CPU | Real GPU |
| --- | --- | --- |
| Codex | Failed: malformed tool arguments / reasoning continuation | Failed: malformed tool arguments / reasoning continuation |
| Claude Code | Failed: system role | Failed: system role |
| OpenCode | Passed | Passed |

The [previous pins](https://github.com/redhat-et/secure-single-server/blob/36690004af49955937e905339b1830617282a9e1/configs/vllm/images.env)
and private baseline evidence are retained for comparison. Moving to 0.30 also
exposed Claude's oversized default output request; the launcher correction was
then tested on CPU and GPU. No Praxis image or API translation change was needed.

### Bootc OpenShell

| Harness / provider | Deployment | Real CPU | Real GPU | Evidence scope |
| --- | --- | --- | --- | --- |
| OpenCode / Qwen | Bootc all-in-one | Passed | Passed | Streaming, tool-created file with independent readback, explicit network denials and lifecycle checks |

[Bootc evidence](../../bootc/VLLM-VALIDATION.md), also with thinking disabled, uses OpenCode 1.18.31, different
OS/service images, networking, model route and tool task. It is useful for the
mutable-host qualification method but does not qualify that deployment.
Bootc image/recipe checks for Codex/OpenClaw do not establish Praxis inference.
No Claude or real cloud-provider sandbox pass is recorded here.

## Backend diagnostics and fix ownership

Bypass controls locate failures without qualifying a harness through Praxis.

| Harness | Backend | CPU bypass | GPU bypass | Fix ownership / next step |
| --- | --- | --- | --- | --- |
| Codex | vLLM 0.19, thinking on | Missing reasoning `id` rejected | Malformed tool arguments and continuation rejection reproduced | vLLM; upgrade fixes GPU native tasks |
| Codex | vLLM 0.30 | Not run for ID drift | Streamed/final tool IDs differ; arguments match | vLLM final response builder; add stable-ID regression |
| Claude Code | vLLM 0.19 | Captured CLI request rejected | Captured CLI request rejected | vLLM system-role support; fixed by upgrade plus launcher output limit |

The current-image CPU and GPU Codex tasks pass. Earlier CPU task loops did not
establish a backend-specific protocol defect. Keep model/task reliability
separate from the reproducible stream-ID bug.

The [current bug guide](vllm-debugging.md) covers the latest image pair only.
The strict GPU replay still changes IDs through Praxis PR #40 and directly
against vLLM 0.30; three completed tool calls have matching arguments but
different final IDs. This remains a backend issue. Translation is not enabled.

## Host and policy checks

| Check | Recorded result |
| --- | --- |
| AWS/RHEL installation, native mocks, provider additions | Passed on CPU/GPU all-in-one and the earlier CPU remote-gateway with memory quotas |
| Mock reboot recovery | Passed on both current all-in-one hosts; GPU also recovered after the driver/kernel update |
| Real vLLM 0.30 reboot recovery | Previous Praxis image: passed on GPU; current-image reboot test and CPU remain not run |
| Mock removal | Passed on CPU/GPU all-in-one: no mock service, fixture files, synthetic cloud secrets or published vLLM port |
| Ordinary user | CPU/GPU smoke CLIs use `praxis-smoke`; personal `praxis-user` SSH login and pinned CLI installation passed on both hosts, with no sudo or service-file access |
| Valkey | Current-image provider and TLS/JWT container tests passed for both roles; fresh RHEL lifecycle remains untested |
| OpenShell CPU/memory limits | Offline defaults/overrides pass; GPU sandbox and supervisor both have effective 2 CPU / 4 GiB limits |
| OpenShell kernel/dev-server behavior | `bootc/test-kernel` exists; no runtime result for this AWS pair |

The administrator manages services and upstream secrets. Local direct users
share the gateway's quota pool. OpenShell's loopback management API now requires TLS/mTLS; the service operator
identity does not establish private sandbox ownership for ordinary users.
See [account setup](../quickstarts/all-in-one/accounts.md) and the
[OpenShell boundary](../../openshell/docs/threat-model.md).

## Run and record the next results

Use [mock smoke tests](rhel-smoke.md), then [real-provider tests](rhel-real.md).
Begin new real qualification with `--harness opencode`; then test Codex and
Claude against the matching backend's recorded results. Do not count failures as expected passes.

For each new result record scenario, CPU/GPU, execution location, harness,
provider/API, thinking mode, mock or real backend, exact pins, streamed tool/continuation
result, independent generated-test result and evidence path. Keep translated
and native API modes separate. Add results only to their matching table cells.

Current-image evidence is in `.state/rhel-USER-HOST/praxis40-real-evidence.tar.gz`,
`model-menus.log`, `openshell-node-task.log` and the OpenShell phase logs.
Workstation source hashes live in the same directory; VM CLI logs
and result JSON live in `/var/lib/praxis-rhel-smoke/`. GPU bypass evidence is in
private baseline archives and captured-request directories. Private artifacts stay out of Git.
