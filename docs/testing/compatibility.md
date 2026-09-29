# Compatibility and test matrix

Results cover the [current tested stack](#tested-stack), except the retained mock
passes noted below. Every acceptance path goes through Praxis. **Direct** means
an ordinary OS user outside OpenShell; OpenClaw is included only in OpenShell.

| Section / columns | Test procedure and recorded coverage |
| --- | --- |
| All-in-one: Mock | [Native mock smoke](rhel-smoke.md#1-install-and-test): recorded tool queries passed; native rerun with the current Praxis image is pending |
| All-in-one: Real CPU / Real GPU | [Real Qwen runner](rhel-real.md#2-test-real-inference): API checks and native file/test tasks on each VM; [interactive model selectors](harnesses.md#model-selector-checks) checked separately |
| All-in-one: Real OpenAI / Real Anthropic | [Provider setup](rhel-real.md#3-add-openai-to-existing-praxis), then [manual tool task](harnesses.md#acceptance-task) and [selector checks](harnesses.md#model-selector-checks); not run |
| Remote-gateway: all columns | [External client setup](harnesses.md#remote-gateway-client), then the same manual task and selector checks; not run |
| OpenShell: Mock / Real CPU / Real GPU / cloud | [Sandbox tool task](openshell-manual.md#2-qualify-actual-sandboxed-harnesses) and [selectors](harnesses.md#model-selector-checks); only real Qwen OpenCode has native task results |
| OpenShell: infrastructure | [Installation, API and policy probes](openshell-manual.md#1-run-installation-inference-and-policy-probes); these do not qualify native harness rows |

**Tool query** requires streamed inference, tool execution, continuation after
the tool result, generated files and independently passing tests. **`/model`**
(or OpenCode's **`/models`**) checks that the intended model is visible in the
interactive selector. Inference after changing the menu selection is **Not run**
everywhere; task tests launch the model explicitly. A model-list API response
alone does not qualify a menu. Praxis has no combined catalog across providers.

**Passed** = the named check succeeded. **Failed** = it ran and failed.
**Unverified** = attempted, but evidence is inconclusive. **Not run** = no result
on this stack. **Blocked [n]** = a prerequisite is missing; reasons follow the table.

## All-in-one

Harnesses run as ordinary users on the same RHEL VM as Praxis and vLLM.

**Mock tool-query passes** retain the last native results on both hosts,
recorded before the Praxis image update. They have not been repeated with
the current image; model-selector checks are separate.

**Qwen3-8B / vLLM**

| Harness | Check | Mock | Real CPU | Real GPU |
| --- | --- | --- | --- | --- |
| Codex | Tool query | Passed | Passed | Passed |
| Codex | `/model` | Not run | Failed [1] | Failed [1] |
| Claude Code | Tool query | Passed | Passed | Passed |
| Claude Code | `/model` | Not run | Passed [2] | Passed [2] |
| OpenCode | Tool query | Passed | Passed | Passed |
| OpenCode | `/models` | Not run | Passed [2] | Passed [2] |

1. Codex shows its built-in OpenAI catalog; Qwen is absent. Explicit
   `--model qwen3-8b` works. A custom catalog integration is still needed.
2. Claude shows configured Qwen aliases; OpenCode shows configured
   `praxis/qwen3-8b`. These are configured entries, not automatic discovery.

All six native API probes (Chat, Responses and Messages, each JSON/SSE) and
`/vllm/v1/models` pass on both backends. A stricter GPU Responses replay still
finds streamed/final tool-ID drift, also reproduced directly against vLLM.
See the [current bug and fix candidate](vllm-debugging.md#responses-tool-ids-change-between-stream-and-final-response).

**OpenAI models**

| Harness | Check | Mock | Real OpenAI |
| --- | --- | --- | --- |
| Codex | Tool query | Passed | Not run |
| Codex | `/model` | Not run | Not run |
| Claude Code | Tool query | Not run [1] | Not run [1] |
| Claude Code | `/model` | Not run [1] | Not run [1] |
| OpenCode | Tool query | Passed | Not run |
| OpenCode | `/models` | Not run | Not run |

1. Claude → OpenAI needs API translation/integration; the current launcher
   supports Claude's native Messages API only. This is a qualification target.

**Anthropic models**

| Harness | Check | Mock | Real Anthropic |
| --- | --- | --- | --- |
| Codex | Tool query | Not run [1] | Not run [1] |
| Codex | `/model` | Not run [1] | Not run [1] |
| Claude Code | Tool query | Passed | Not run |
| Claude Code | `/model` | Not run | Not run |
| OpenCode | Tool query | Passed | Not run |
| OpenCode | `/models` | Not run | Not run |

1. Codex → Anthropic needs API translation/integration; the current launcher
   uses Responses for Codex. This is a qualification target.

No real cloud account or external-provider-only VM is qualified. Cloud models
have no local CPU/GPU distinction. API translation is not enabled or tested.

## Remote-gateway

An ordinary user runs the harness on a **separate client machine**, through
HTTPS/JWT to Praxis. CPU/GPU identifies the gateway's vLLM backend. No current
RHEL variant has completed this external-client qualification. The RHEL runner's
on-gateway CLI checks and separate public API probes do not qualify these rows.

**Qwen3-8B / vLLM**

| Harness | Check | Mock | Real CPU | Real GPU |
| --- | --- | --- | --- | --- |
| Codex | Tool query | Not run | Not run | Not run |
| Codex | `/model` | Not run | Not run | Not run |
| Claude Code | Tool query | Not run | Not run | Not run |
| Claude Code | `/model` | Not run | Not run | Not run |
| OpenCode | Tool query | Not run | Not run | Not run |
| OpenCode | `/models` | Not run | Not run | Not run |

**OpenAI models**

| Harness | Check | Mock | Real OpenAI |
| --- | --- | --- | --- |
| Codex | Tool query | Not run | Not run |
| Codex | `/model` | Not run | Not run |
| Claude Code | Tool query | Not run [1] | Not run [1] |
| Claude Code | `/model` | Not run [1] | Not run [1] |
| OpenCode | Tool query | Not run | Not run |
| OpenCode | `/models` | Not run | Not run |

1. Claude → OpenAI needs API translation/integration before qualification.

**Anthropic models**

| Harness | Check | Mock | Real Anthropic |
| --- | --- | --- | --- |
| Codex | Tool query | Not run [1] | Not run [1] |
| Codex | `/model` | Not run [1] | Not run [1] |
| Claude Code | Tool query | Not run | Not run |
| Claude Code | `/model` | Not run | Not run |
| OpenCode | Tool query | Not run | Not run |
| OpenCode | `/models` | Not run | Not run |

1. Codex → Anthropic needs API translation/integration before qualification.

## OpenShell

**Ordinary-user access is blocked by [#12](https://github.com/redhat-et/secure-single-server/issues/12)**
(enrollment and workspace ownership). The results below use the locked
`openshell-svc` management identity; harnesses run as the sandbox user.
They qualify service-operator testing only, not personal-user access.

**All-in-one: Qwen3-8B / vLLM**

| Harness | Check | Mock | Real CPU | Real GPU |
| --- | --- | --- | --- | --- |
| Codex | Tool query | Blocked [1] | Blocked [1] | Blocked [1] |
| Codex | `/model` | Blocked [1] | Blocked [1] | Blocked [1] |
| Claude Code | Tool query | Blocked [2] | Blocked [2] | Blocked [2] |
| Claude Code | `/model` | Blocked [2] | Blocked [2] | Blocked [2] |
| OpenCode | Tool query | Not run | Failed [3] | Passed |
| OpenCode | `/models` | Not run | Unverified [4] | Unverified [4] |
| OpenClaw | Tool query | Blocked [1] | Blocked [1] | Blocked [1] |
| OpenClaw | Model selector | Blocked [1] | Blocked [1] | Blocked [1] |

1. Codex and OpenClaw recipes lack Praxis adapters and reject `--config`.
2. Claude needs a pinned sandbox image and recipe.
3. CPU OpenCode creates files but its generated Node tests fail independently.
   CLI exit zero is insufficient. GPU passes all three generated Node tests.
   The sandbox image has no Python; this task differs from the direct Python task.
4. Headless `opencode models praxis` lists Qwen on both backends. Interactive
   `/models` attempts ended before the menu could be verified.

**All-in-one: OpenAI models**

| Harness | Check | Mock | Real OpenAI |
| --- | --- | --- | --- |
| Codex | Tool query | Blocked [1] | Blocked [1] |
| Codex | `/model` | Blocked [1] | Blocked [1] |
| Claude Code | Tool query | Not run [2] | Not run [2] |
| Claude Code | `/model` | Not run [2] | Not run [2] |
| OpenCode | Tool query | Not run | Not run |
| OpenCode | `/models` | Not run | Not run |
| OpenClaw | Tool query | Blocked [1] | Blocked [1] |
| OpenClaw | Model selector | Blocked [1] | Blocked [1] |

1. Codex and OpenClaw need Praxis adapters.
2. Claude → OpenAI is an untested target requiring a sandbox image/recipe and
   API translation/integration.

**All-in-one: Anthropic models**

| Harness | Check | Mock | Real Anthropic |
| --- | --- | --- | --- |
| Codex | Tool query | Not run [1] | Not run [1] |
| Codex | `/model` | Not run [1] | Not run [1] |
| Claude Code | Tool query | Blocked [2] | Blocked [2] |
| Claude Code | `/model` | Blocked [2] | Blocked [2] |
| OpenCode | Tool query | Blocked [3] | Blocked [3] |
| OpenCode | `/models` | Blocked [3] | Blocked [3] |
| OpenClaw | Tool query | Blocked [3] | Blocked [3] |
| OpenClaw | Model selector | Blocked [3] | Blocked [3] |

1. Codex → Anthropic is an untested target requiring a Praxis adapter and
   API translation/integration.
2. Claude needs a pinned sandbox image and recipe.
3. Anthropic Messages adapters are missing; OpenClaw also lacks a Praxis adapter.

**Remote-gateway: sandbox clients**

OpenShell runs on the separate client host. These statuses apply to mock and
real Qwen CPU/GPU, OpenAI and Anthropic routes.

| Harness | Tool query | Model selector |
| --- | --- | --- |
| Codex | Blocked [1] | Blocked [1] |
| Claude Code | Blocked [1] | Blocked [1] |
| OpenCode | Blocked [1] | Blocked [1] |
| OpenClaw | Blocked [1] | Blocked [1] |

1. Remote recipes need HTTPS/CA/JWT adapters and gateway egress policy, in
   addition to the harness/provider prerequisites above. No runtime results exist.

### Infrastructure checks on all-in-one

| Check | CPU | GPU |
| --- | --- | --- |
| Addon install, authenticated management, sandbox create/SSH | Passed | Passed |
| Management TLS rejects missing client certificate | Passed | Passed |
| Gateway telemetry disabled | Passed | Passed |
| Praxis model-list API from sandbox | Not run | Passed |
| Standalone streaming Qwen API probe | Not run | Passed |
| Nonstreaming Qwen API probe | Failed [1] | Failed [1] |
| Controlled network positive control | Passed | Passed |
| Controlled denial proof | Failed [2] | Failed [2] |
| Effective sandbox and supervisor limits | Not run | Passed: 2 CPU / 4 GiB |

1. Nonstreaming POST closes before a response. The identical GPU request from
   the host returns HTTP 200; streaming in the sandbox works. This points to
   the sandbox transport path, but the exact cause is unconfirmed.
2. The allowed request returns the controlled server's expected 401 and is
   recorded there. The denied request returns `ENOTFOUND`, not an explicit policy
   denial. The qualification fails; this does not prove confinement.

### OpenShell blockers and open issues

| Issue | Remaining gap |
| --- | --- |
| [#12: identity/workspaces](https://github.com/redhat-et/secure-single-server/issues/12) | Blocks ordinary-user sandbox access; operator results do not qualify it |
| [#13: provider profiles](https://github.com/redhat-et/secure-single-server/issues/13) | Managed provider attachment and credential lifecycle; missing harness adapters remain separate gaps |
| [#14: endpoint rules/TLS](https://github.com/redhat-et/secure-single-server/issues/14) | Method/path confinement and TLS on the sandbox-to-Praxis hop; basic operator inference remains testable |
| [#23: structured evidence](https://github.com/redhat-et/secure-single-server/issues/23), [#24: policy proofs](https://github.com/redhat-et/secure-single-server/issues/24) | Reliable evidence for the inconclusive denial check |

No focused issue currently tracks the nonstreaming transport failure or missing
harness adapters. The issues above are not confirmed explanations for that failure.

## Tested stack

The AWS all-in-one results use RHEL 9.8 x86_64, Podman 5.8.2, enforcing SELinux
and memory quotas. API forwarding is native; translation remains untested.

- Praxis: `quay.io/opendatahub/praxis-experimental@sha256:227d421e963c477038a884dc51ec880c5d0afa30098ae31028ecf85e963e40d5`,
  source `019aa849a219e5c881d69e4a40a1fc190bd6c404`.
- vLLM 0.30.0, Qwen3-8B, **thinking enabled**;
  [CPU/GPU image and model pins](../../configs/vllm/images.env).
- Direct CLIs: Codex 0.157.1, Claude Code 2.1.283, OpenCode 1.18.32
  ([pins](../../configs/common/harness-versions.json)).
- OpenShell 0.1.2-rhaiv.0; sandbox OpenCode 1.18.31 and Node.js 26.9.0
  ([image pins](../../openshell/configs/images.env)).

Current-image [container contract tests](../../tests/mocked-provider.py) pass for
both gateway roles with memory and Valkey, including TLS/JWT and mocked provider
additions. They do not populate native CLI, menu or RHEL lifecycle cells.

## CPU/GPU limits and measured performance

| Setting or observation | All-in-one CPU | All-in-one GPU |
| --- | --- | --- |
| AWS host | `m7i.4xlarge`, 16 vCPU / 64 GiB | `g6.2xlarge`, NVIDIA L4 / 32 GiB |
| Model precision / server context | BF16 / 16,384 tokens | BF16 / 16,384 tokens |
| Concurrent inference requests | 1; additional requests queue | 1; additional requests queue |
| OpenCode / Claude output budget | 4096 tokens, including thinking | 4096 tokens, including thinking |
| Codex context / auto-compaction threshold | 16,384 / 12,288 tokens | 16,384 / 12,288 tokens |
| Codex output budget | Remaining context; no separate output cap in the pinned CLI | Same |
| Automated real CLI deadline | 60 minutes per harness | 30 minutes per harness |
| Observed generation rate | About 3 tokens/s | About 15 tokens/s |
| Codex tool query | 9.1 minutes | 1.9 minutes |
| Claude Code tool query | 11.0 minutes | 2.2 minutes |
| OpenCode tool query | 6.4 minutes | 1.5 minutes |

Durations are one complete direct-host task per harness/backend. Rates are
single-request samples, not sustained benchmarks; task times also include
reasoning, prompt processing and tools. Expect minutes per CPU tool task.
The runner records limits and elapsed times; timeouts fail and thinking stays on.

## Evidence and recording results

Private workstation evidence lives in `.state/rhel-USER-HOST/`:
`praxis40-real-evidence.tar.gz` for direct real tasks, `model-menus.log` for
selectors, `openshell-node-task.log` for sandbox tasks and OpenShell phase logs
for infrastructure probes. VM logs and result JSON live in
`/var/lib/praxis-rhel-smoke/`. Keep private artifacts out of Git.

Record scenario, execution location, user/access mode, provider, CPU/GPU where
applicable, exact image/CLI pins, tool/test result, menu result and evidence path.
A new image or configuration needs fresh qualification in its matching cells.
