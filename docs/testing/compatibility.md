# Compatibility and test matrix

Use this matrix to choose a working test path and locate remaining fixes.
Results apply to the pinned versions and tested deployments below. The
[debug plan](vllm-debugging.md) defines the API paths, CPU/GPU controls, PR #40
image comparison, translation experiments and upstream fix candidates.

**Start with OpenCode → Praxis → real Qwen.** Codex → OpenAI and Claude Code →
Anthropic are configured native-provider paths with passing mock tests; real
cloud calls still need manual validation. Codex/Claude tool tasks against the
pinned real vLLM backend are failing and are not qualified for use.

## Tested scope

- All-in-one: AWS `g6.2xlarge`, NVIDIA L4, real GPU vLLM.
- Remote-gateway: AWS `m7i.4xlarge`, real CPU vLLM, HTTPS/JWT access.
- Both: RHEL 9.8 x86_64, Podman 5.8.2, enforcing SELinux, memory quotas.
- Backend: vLLM 0.19.0 with Qwen3-8B. Exact image digests and model revision:
  [backend pins](../../configs/vllm/images.env).
- Native clients: Codex 0.157.1, OpenCode 1.18.32, Claude Code 2.1.283;
  [CLI pins](../../tests/rhel/harness-versions.json).

CPU all-in-one and GPU remote-gateway are configurable alternatives; those
reversed hardware/scenario combinations have not been qualified by this run.

## Harness and provider matrix

Every path in this table goes through Praxis. **Mock passed** means the native
CLI completed a tool task against a synthetic backend, including credential
handling and tool continuation. **Real smoke passed** means the real model
created the specified files, ran unittest through a CLI tool and passed
independent file/test checks. It does not establish general coding reliability.

| Harness | Backend | Native API | Mock test on both VMs | Real-provider result |
| --- | --- | --- | --- | --- |
| OpenCode | Qwen/vLLM | Chat Completions | Passed | Smoke passed on GPU all-in-one and CPU remote-gateway |
| Codex | Qwen/vLLM | Responses | Passed | Failed on both: streamed tool response does not complete |
| Claude Code | Qwen/vLLM | Messages | Passed | Failed on both: backend rejects a system-role message |
| Codex | OpenAI | Responses | Passed | Not tested with real credentials; intended native-provider path |
| OpenCode | OpenAI | Chat Completions | Passed | Not tested with real credentials; intended native-provider path |
| Claude Code | Anthropic | Messages | Passed | Not tested with real credentials; intended native-provider path |
| OpenCode | Anthropic | Messages | Passed | Not tested with real credentials; intended native-provider path |

Codex → Anthropic and Claude Code → OpenAI are not configured by this launcher.
Praxis preserves the selected native API; this workflow supplies no translation
between Responses, Chat Completions and Messages. A vLLM model must implement
the particular API and tool behavior required by the client.

## CPU and GPU results

| Backend / scenario | Basic APIs through Praxis | OpenCode task through Praxis | Codex / Claude tasks through Praxis | Direct Codex / Claude control |
| --- | --- | --- | --- | --- |
| GPU / all-in-one | Passed | Passed | Both failed | Both failed |
| CPU / remote-gateway | Passed | Passed | Both failed | Not yet run |
| CPU / additional all-in-one | Not yet run | Not yet run | Not yet run | Not yet run |

The direct GPU result does not substitute for the pending direct CPU control.

## Execution modes

Native tests and sandbox tests are separate acceptance results. All inference
acceptance goes through Praxis; direct vLLM calls are only diagnostic controls.

| Harness | Ordinary host account | OpenShell sandbox through Praxis |
| --- | --- | --- |
| OpenCode | Mock Qwen/OpenAI/Anthropic passed; real Qwen CPU/GPU passed | Real Qwen CPU/GPU passed on **bootc**. Mutable AWS route/config tests pass; live sandbox/tool acceptance remains pending. OpenAI/Anthropic sandbox mocks remain pending. |
| Codex | Mock Qwen/OpenAI passed; real Qwen fails as described above | Standalone image/recipe exists; Praxis adapter is not implemented (`--config` rejects it). No integrated inference result. |
| Claude Code | Mock Qwen/Anthropic passed; real Qwen fails as described above | No pinned sandbox image/recipe or integrated inference result. |
| OpenClaw | No native launcher/test in this workflow | Standalone image/recipe exists; Praxis adapter is not implemented (`--config` rejects it). No integrated inference result. |

[PR #6's bootc evidence](../../bootc/VLLM-VALIDATION.md) covers OpenCode 1.18.31
streaming, a real tool-created file with independent readback, and explicit
network denials on CPU/GPU. Its images, network layout, model route and task
differ from this mutable RHEL runner, so it cannot qualify that runner's
OpenShell path. The mutable optional mock phase currently checks a sandbox API
call and controlled policy denial, rather than a native CLI tool task.

OpenClaw is included in the target matrix, starting with OpenShell. Its existing
build/schema/recipe tests do not establish provider compatibility. This is a
test-scope choice, not a requirement that OpenClaw can only run in OpenShell.
Future results must record harness, execution mode, provider/API, CPU/GPU,
scenario, image/CLI pins, tool continuation, usage and network-denial checks.

## Account boundaries

The administrator installs services and manages upstream secrets. The native
runner creates `praxis-smoke`, installs CLIs in its home and executes them using
that ordinary account; it checks that service configuration is unreadable.
[Manual setup](../quickstarts/all-in-one/accounts.md) creates a separate SSH login without granting sudo
or service groups. Local users share the gateway's configured quota pool.

Remote-gateway automation runs its native CLIs as an ordinary user on the VM
against HTTPS/JWT, plus a public TLS/JWT probe from the workstation. Full native
CLI runs from an external client are a separate [manual check](harnesses.md).

OpenShell uses the locked `openshell-svc` service owner. Ordinary users can
register the loopback client and enter sandboxes without sudo, but the current
management API trusts all local users. This remains a trusted-host experiment,
not per-user sandbox ownership or workspace isolation. See the
[OpenShell boundary](../../openshell/docs/threat-model.md).

## What bypassing Praxis proves

The normal path is `CLI → Praxis → vLLM → Qwen`. The diagnostic path was
`CLI → vLLM → Qwen`, using the same GPU backend and pinned CLI versions.
Codex and Claude still failed. These failures therefore do not require Praxis
to occur; they are not evidence that Praxis lacks the corresponding API.

Praxis routing and native tool transport passed with mocks. Real Qwen also
passed basic text requests through Responses, Chat Completions and Messages,
with both JSON and streaming responses. Full CLI tool requests exercise more
of the backend API and expose failures that those basic requests do not.

The direct result narrows the problem to the pinned backend/client combination.
It does not declare every vLLM version incompatible with these harnesses, or
prove that every possible request through Praxis is correct.

## Fix locations and acceptance

| Failure or gap | Evidence | Where to investigate or change |
| --- | --- | --- |
| Codex → vLLM tool streaming | Through-Praxis failure on CPU/GPU; direct failure on GPU. CPU traceback constructs `ResponseFunctionToolCallItem` with `arguments=None` in `responses/serving.py::_process_simple_streaming_events`. | Start with vLLM's Responses streaming implementation. Reduce to a minimal streamed function-call request; fix upstream or select a verified compatible backend/client pin, then update this repository's pins. |
| Claude Code → vLLM Messages | Through-Praxis failure on CPU/GPU and the same HTTP 400 directly on GPU: `body.messages[1].role=system`, expected `user`/`assistant`. Basic Messages requests with top-level `system` pass. | Inspect the native CLI request and vLLM's Messages validation/conversion. Determine whether the change belongs in vLLM, the CLI integration or its pin; direct reproduction alone does not identify which creates the invalid role. |
| Broader OpenCode/Qwen coding reliability | Explicit smoke passes; open-ended attempts also produced incorrect tests or repeated edits. | Evaluate the model, prompt and tool behavior separately. Keep smoke permission instructions accurate and retain normal interactive approvals. Do not treat a model mistake as a proxy transport failure. |
| Real OpenAI/Anthropic acceptance | Native mock paths pass; no real cloud credentials used. | Run the manual provider/harness combinations above with chosen accessible models. There is no demonstrated cloud-provider defect to fix yet. |

For any candidate Codex/Claude fix, require successful streamed tool calls,
tool-result continuation, final usage, and independently passing generated
tests on CPU and GPU through Praxis. Compare directly with the backend first.
A failure that passes directly but fails through Praxis then needs a proxy or
gateway-configuration investigation. No cloud fallback should hide a Qwen error.

## Deployment and test coverage

| Check | Result and boundary |
| --- | --- |
| AWS provisioning and RHEL installation | Passed for the two tested hardware/scenario combinations |
| Native mocks and independent provider additions | Passed on both RHEL VMs with memory quotas |
| Real Qwen basic API contracts | All six JSON/streaming checks passed on both VMs |
| Remote public TLS/JWT | Valid caller accepted; invalid caller rejected |
| Transition from mocks to real Qwen | Passed; mock service, fixture files and synthetic cloud secrets removed; no vLLM host port |
| Valkey provider configurations | Container tests passed for both scenarios; fresh RHEL lifecycle acceptance remains untested |
| OpenShell with Praxis | Bootc OpenCode/Qwen CPU/GPU passed; mutable AWS sandbox/tool qualification pending |
| OpenClaw | Standalone build/recipe contracts only; integrated Praxis adapter and runtime acceptance pending |
| Sandbox CPU/memory limits | Merged create helper passes 2 CPUs/4 GiB by default; defaults/overrides pass offline checks. Effective runtime limits on these AWS VMs remain unverified. |
| Kernel/sandbox dev-server behavior | Merged `bootc/test-kernel` records Landlock/kernel/seccomp behavior. No result recorded for this AWS pair; bootc's prior inference pass does not qualify socket write-back or dev-server workloads. |

## Run the checks

Use [mock smoke testing](rhel-smoke.md), then [real-provider testing](rhel-real.md).
The real test runs basic API checks plus the selected harness. Use
`--harness opencode` for the passing smoke path; select `codex` or `claude` to
reproduce a known failure, or omit the selector to run all three. Failures
remain nonzero; they are not counted as expected passes.

Use [manual harness commands](harnesses.md) for real cloud providers and broader
model tasks. Workstation logs and source hashes are in `.state/rhel-USER-HOST/`;
VM CLI logs and result JSON are in `/var/lib/praxis-rhel-smoke/`. Direct diagnostic
logs are `direct-codex.log` and `direct-claude.log` on the GPU VM. These private
run artifacts are not committed documentation.
