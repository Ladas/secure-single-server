# Compatibility and test matrix

Every acceptance path below includes Praxis. **Direct** means the harness runs
under an ordinary OS account, outside OpenShell. **Bypass** means a diagnostic
request to vLLM without Praxis; it is never an acceptance result.

- **Passed**: native CLI streaming, a tool task and tool-result continuation
  passed. Real Qwen smoke also requires generated files and independent unittest
  checks. This is functional smoke coverage, not general coding reliability.
- **Failed**: the test ran and failed; the command returns nonzero.
- **Not run**: no runtime result for that exact combination.
- **Blocked**: a required launcher, sandbox image or provider adapter is missing.

Start qualification with **OpenCode → Praxis → Qwen**. Real cloud calls
remain untested; passing mocks do not qualify real OpenAI/Anthropic accounts.

## Thinking mode

Mutable RHEL installs enable **Qwen thinking**. The all-in-one tables below
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

Mutable RHEL vLLM is pinned to 0.30.0 with Qwen3-8B; CPU/GPU have
[separate image digests](../../configs/vllm/images.env). Direct harness pins are
Codex 0.157.1, OpenCode 1.18.32 and Claude Code 2.1.283
([version file](../../tests/rhel/harness-versions.json)). Keep results for a new
image, API translation mode, CLI pin or deployment separate from this baseline.

## All-in-one

Both variants run Praxis and their selected CPU/GPU vLLM on the same host.
OpenShell is a separate execution mode on that host after the direct baseline.
**CPU remote-gateway results do not populate CPU all-in-one cells.**

### Direct harnesses as ordinary users: vLLM 0.30

| Harness | Provider | GPU mock | GPU real | CPU mock | CPU real |
| --- | --- | --- | --- | --- | --- |
| OpenCode | Qwen/vLLM | Passed | Passed | Passed | Passed |
| Codex | Qwen/vLLM | Passed | Passed | Passed | Failed: tool-policy/task loops with corrected settings |
| Claude Code | Qwen/vLLM | Passed | Passed | Passed | Passed |
| Codex | OpenAI | Passed | Not run | Passed | Not run |
| OpenCode | OpenAI | Passed | Not run | Passed | Not run |
| Claude Code | Anthropic | Passed | Not run | Passed | Not run |
| OpenCode | Anthropic | Passed | Not run | Passed | Not run |
| OpenClaw | Qwen/OpenAI/Anthropic | Blocked | Blocked | Blocked | Blocked |

OpenClaw has no direct launcher/test in this workflow; its first integration
will use OpenShell. Codex → Anthropic and Claude → OpenAI are not configured.
Codex uses Responses, OpenCode uses Chat Completions (Messages for Anthropic),
and Claude uses Messages. Current routes forward the native API without translation.

All six basic JSON/SSE API checks passed on both backends. GPU Codex passed
three consecutive file/test tasks, including one after a host reboot, and reports
reasoning-token usage; OpenCode emits separate reasoning events; Claude emits
thinking, tool-use, tool-result and final-text blocks. These are native API
results through Praxis, with no translation filters. Single smoke passes do
not establish general model reliability or qualify OpenShell. A stricter GPU
Responses capture and private backend replay found that streamed tool IDs differ
from the final response's IDs, even though each tool's arguments match and Codex
completes its task. Track
that protocol gap separately from CLI smoke success.

### Earlier vLLM 0.19 comparison

The same Praxis image/model with thinking enabled produced these results:

| Harness | GPU real Qwen | CPU real Qwen |
| --- | --- | --- |
| OpenCode | Passed | Passed |
| Codex | Failed: malformed tool arguments / reasoning continuation | Failed: malformed tool arguments / reasoning continuation |
| Claude Code | Failed: system role | Failed: system role |

The [previous pins](https://github.com/redhat-et/secure-single-server/blob/36690004af49955937e905339b1830617282a9e1/configs/vllm/images.env)
and private baseline evidence are retained for comparison. Moving to 0.30 also
exposed Claude's oversized default output request; the launcher correction was
then tested on CPU and GPU. No Praxis image or API translation change was needed.

### CPU/GPU limits and measured performance

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
| Recorded OpenCode file/test task with the final launcher | 12.6 minutes | 1.7 minutes |
| Recorded Claude file/test task, seven CLI turns | 10.2 minutes | 2.4 minutes |
| Consequence for manual use | Expect minutes per tool task; prefer GPU for interactive work | Faster, but still limited by this model and context size |

Rates are observed single-request server samples, not sustained benchmarks or
latency guarantees. They exclude prompt processing, tool execution and queueing.
Durations are complete native runs of the same task, one sample per backend
and harness. Reasoning length and model decisions vary, so these are not pure
hardware comparisons. Both OpenCode runs used the final launcher and passed
file creation, native unittest execution and independent checks.
CPU Codex first timed out at 30 minutes with fallback client settings. With
corrected context settings, it repeatedly requested forbidden escalation.
A separate instruction experiment avoided that request but called an
unadvertised tool and repeatedly ran an empty test suite. Both diagnostic loops
were stopped and recorded as failures, not deadline expirations. They do not
establish a CPU-specific protocol defect; see the [debug plan](vllm-debugging.md#cpu-codex-task-failures).

The runner detects CPU/GPU from the installed backend and records its deadline, client
limits, API-check duration and each harness's elapsed time in result JSON.
Timeouts remain failures, and thinking is never disabled to meet a deadline.
Mocks retain a three-minute deadline per harness.

### OpenShell harnesses on the same host

These are **mutable AWS RHEL** results. A passing direct-host test, recipe
rendering test or Ready sandbox cannot populate a sandbox tool-test cell.

| Harness | Provider | GPU mock | GPU real | CPU mock | CPU real |
| --- | --- | --- | --- | --- | --- |
| OpenCode | Qwen/vLLM | Not run | Not run | Not run | Not run |
| OpenCode | OpenAI | Not run | Not run | Not run | Not run |
| OpenCode | Anthropic | Blocked | Blocked | Blocked | Blocked |
| Codex | Qwen/vLLM | Blocked | Blocked | Blocked | Blocked |
| Codex | OpenAI | Blocked | Blocked | Blocked | Blocked |
| Claude Code | Qwen/Anthropic | Blocked | Blocked | Blocked | Blocked |
| OpenClaw | Qwen/OpenAI/Anthropic | Blocked | Blocked | Blocked | Blocked |

OpenCode's Qwen/OpenAI config rendering passes offline tests. The mutable Qwen
route is `/vllm/v1`; the cloud route is `/v1`. The Anthropic sandbox adapter is
missing. Codex and OpenClaw have standalone images/recipes but reject Praxis
`--config`; those adapters are missing. Claude needs a pinned image and recipe.

The optional `--phase openshell` currently checks a sandbox API request and
controlled policy denial. It does **not** run the native CLI file/test task and
cannot produce a Passed cell above. Use the
[manual sandbox guide](openshell-manual.md) for the current experiment.

### Separate bootc OpenShell evidence

| Deployment | Harness/provider through Praxis | Real CPU | Real GPU | Evidence scope |
| --- | --- | --- | --- | --- |
| Bootc all-in-one | OpenCode / Qwen | Passed | Passed | Streaming, tool-created file with independent readback, explicit network denials and lifecycle checks |

[Bootc evidence](../../bootc/VLLM-VALIDATION.md), also with thinking disabled, uses OpenCode 1.18.31, different
OS/service images, networking, model route and tool task. It is useful for the
mutable-host qualification method but does not qualify that deployment.
Bootc image/recipe checks for Codex/OpenClaw do not establish Praxis inference.
No Claude or real cloud-provider sandbox pass is recorded here.

## Remote-gateway

The gateway serves HTTPS/JWT. Recorded **CPU gateway VM** results use vLLM 0.19
with thinking disabled. Neither remote-gateway variant has been qualified
with the current vLLM 0.30/thinking-enabled defaults.
Harnesses normally run on separate client machines. Existing automation runs
ordinary-user CLIs on the gateway VM against loopback HTTPS/JWT and separately
probes public TLS/JWT from the workstation. This qualifies the installed CPU
backend/native API path, not a full external-client CLI session.

### Direct harness tests on the CPU gateway VM: vLLM 0.19 baseline

| Harness | Provider | Mock through HTTPS/JWT | Real through HTTPS/JWT |
| --- | --- | --- | --- |
| OpenCode | Qwen/vLLM | Passed | Passed |
| Codex | Qwen/vLLM | Passed | Failed: tool stream |
| Claude Code | Qwen/vLLM | Passed | Failed: system role |
| Codex | OpenAI | Passed | Not run |
| OpenCode | OpenAI | Passed | Not run |
| Claude Code | Anthropic | Passed | Not run |
| OpenCode | Anthropic | Passed | Not run |
| OpenClaw | Qwen/OpenAI/Anthropic | Blocked: no launcher | Blocked: no launcher |

### External clients, direct and OpenShell

| Client execution | Harnesses | Mock | Real | Remaining work |
| --- | --- | --- | --- | --- |
| Ordinary workstation account | OpenCode, Codex, Claude on the provider paths above | Not run | Not run | Run the full CLI task with the public URL, trusted CA and caller JWT |
| Ordinary workstation account | OpenClaw | Blocked | Blocked | Implement a client adapter |
| OpenShell on a separate client host | OpenCode, Codex, Claude, OpenClaw | Blocked | Blocked | Add HTTPS/CA/JWT adapters and gateway egress policy, plus each missing harness recipe/provider integration |

Public TLS/JWT probes passed: a valid caller was accepted and an invalid caller
rejected. These were API probes, not external CLI tool tasks. Follow the
[remote manual commands](harnesses.md#remote-gateway-client). OpenShell belongs on
the client in this scenario; do not install it on remote-gateway to stand in
for an external sandbox test. Current OpenShell recipes target local all-in-one.

## External-provider-only VMs

The `all-in-one-cloud` and `remote-gateway-cloud` AWS presets install no local
vLLM. Fresh runtime qualification of those deployments is **Not run**, for both
direct and OpenShell clients. Earlier OpenAI/Anthropic mock passes above verify
the provider routes on the recorded hosts; real cloud accounts remain untested.

## Backend diagnostics and fix ownership

| Backend/scenario | Basic JSON/SSE APIs through Praxis | Codex bypass control | Claude bypass control |
| --- | --- | --- | --- |
| GPU all-in-one, vLLM 0.19, thinking on | All six checks passed | Captured stream has concatenated tool arguments; continuation rejected | Captured CLI request rejected |
| CPU all-in-one, vLLM 0.19, thinking on | All six checks passed | Reduced reasoning continuation rejected | Captured CLI request rejected |
| CPU remote-gateway, vLLM 0.19, thinking off | All six checks passed | Not run | Not run |
| GPU all-in-one, vLLM 0.30, thinking on | All six checks passed | Valid per-tool arguments, but streamed/final IDs differ | Native CLI passes; no failure to replay |

With vLLM 0.19, both backends reproduce validation failures without Praxis. Claude controls
replay captured CLI requests. Codex uses a captured GPU continuation and a
reduced CPU reasoning item without `id`. Replaying the GPU first request also
reproduces malformed tool argument aggregation without Praxis. These controls
locate failures; they do not qualify full harness behavior. Earlier GPU
thinking-disabled controls also failed. Basic text APIs exercise less than a
native tool task.

| Failure | Observed evidence | Next investigation |
| --- | --- | --- |
| Codex/vLLM 0.19, thinking on | CPU/GPU CLIs report malformed tool arguments, then HTTP 400 for a reasoning continuation missing `id`; GPU bypass reproduces concatenation of arguments from multiple calls | Upgrade backend; vLLM 0.30 native GPU tasks pass. CPU tool-policy behavior is a separate investigation |
| Codex/vLLM 0.19, thinking off | Earlier Responses stream disconnects; traceback constructs `ResponseFunctionToolCallItem(arguments=None)` | Keep this first-tool-delta regression separate from thinking-enabled continuation failures |
| Claude/vLLM 0.19 | HTTP 400 rejects `messages[1].role=system`; basic top-level system requests pass | Upgrade backend and correct the client's output budget; vLLM 0.30 tasks pass on CPU/GPU |
| CPU Codex/Qwen | Corrected settings still produce tool-policy/task loops; explicit permission guidance alone did not fix the task | Compare the same captured request and client tool schema on CPU/GPU; qualify model/client guidance without loosening permissions |
| Codex/vLLM 0.30 | GPU CLI passes, but direct replay changes tool IDs between streamed items and the completed response | Reuse streamed items in vLLM's final response builder; retain a stable-ID regression |
| OpenCode/model quality | Explicit smoke passed; earlier open-ended tasks made errors or looped | Keep transport success separate from model/prompt quality |

The [debug plan](vllm-debugging.md) contains source findings, upstream links,
controlled configuration/image comparisons and acceptance requirements.

## Host and policy checks

| Check | Recorded result |
| --- | --- |
| AWS/RHEL installation, native mocks, provider additions | Passed on CPU/GPU all-in-one and the earlier CPU remote-gateway with memory quotas |
| Mock reboot recovery | Passed on both current all-in-one hosts; GPU also recovered after the driver/kernel update |
| Real vLLM 0.30 reboot recovery | Passed on GPU: all six basic API checks and native Codex task; CPU not run |
| Mock removal | Passed on CPU/GPU all-in-one: no mock service, fixture files, synthetic cloud secrets or published vLLM port |
| Ordinary user | CPU/GPU smoke CLIs use `praxis-smoke`; personal `praxis-user` SSH login and pinned CLI installation passed on both hosts, with no sudo or service-file access |
| Valkey | Provider container tests passed for both roles; fresh RHEL lifecycle remains untested |
| OpenShell CPU/memory limits | Defaults/overrides pass offline checks; effective runtime limits on these AWS hosts remain unverified |
| OpenShell kernel/dev-server behavior | `bootc/test-kernel` exists; no runtime result for this AWS pair |

The administrator manages services and upstream secrets. Local direct users
share the gateway's quota pool. OpenShell's current loopback management API
trusts local users; ordinary login does not establish private sandbox ownership.
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

Workstation logs and source hashes live in `.state/rhel-USER-HOST/`; VM CLI logs
and result JSON live in `/var/lib/praxis-rhel-smoke/`. GPU bypass evidence is in
private baseline archives and captured-request directories. Private artifacts stay out of Git.
