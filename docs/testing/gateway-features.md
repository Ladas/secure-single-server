# Harness feature testing

Track feature support and testing here. Keep provider/backend tool-task results
in [compatibility.md](compatibility.md).

| Feature | Codex | Claude Code | OpenCode | OpenClaw / OpenShell |
| --- | --- | --- | --- | --- |
| Qwen model selection | Generated catalog; new menu check pending | Configured custom entry | Configured Praxis entry | Blocked: missing Praxis adapter |
| Gateway model discovery | Uses configured catalog | Opt-in; filters out Qwen IDs | Uses configured catalog | Not qualified |
| Thinking and context limits | Configured; compaction pending | Medium effort for 27B; compaction pending | Configured; compaction pending | Not qualified |
| Inspect/change token quota | Praxis administrator commands | Same | Same | Same gateway controls; adapter pending |
| CLI quota error and recovery | Mock test available; RHEL pending | Mock test available; RHEL pending | Mock test available; RHEL pending | Blocked |
| Quota persistence | Via Praxis/Valkey | Via Praxis/Valkey | Via Praxis/Valkey | Adapter pending |

“Configured” describes available configuration, not a new interactive test pass.

**Contents:** [Codex](#codex) · [Claude Code](#claude-code) ·
[OpenCode](#opencode) · [OpenClaw / OpenShell](#openclaw--openshell) ·
[Shared gateway checks](#shared-gateway-checks)

Run interactive checks as an [ordinary user](../quickstarts/all-in-one/users.md).
For remote gateways, use a [separate client](harnesses.md#remote-gateway-client)
and add its `--url`, `--token-file` and `--ca-file` options to the launcher.
Choose the installed model in that user terminal:

```console
MODEL=qwen3.8-27b-int4
```

Use `qwen3-8b` instead for the 8B preset. For each selector test, choose the
exact model, run the [file/test task](harnesses.md#acceptance-task), and confirm
the backend request used that model. A menu entry or banner alone is insufficient.

The quota commands below run on the **workstation**, after selecting a
[disposable mock VM](rhel-smoke.md). They use Valkey; use `--profile memory`
only on a VM prepared with that profile. The feature phase refuses real-provider
installations, including the manual Qwen CPU/GPU hosts.

## Codex

### Model selection and limits

```console
praxis-harness codex --provider vllm --model "$MODEL" --print-config
praxis-harness codex --provider vllm --model "$MODEL"
```

Type `/model`, select Qwen, then run the file/test task. The launcher supplies
one configured catalog entry; it does not discover models from `/v1/models`.
Check context and compaction settings against the installed vLLM limits.
Repeat after a fresh launch, session resume and actual compaction.

### Quota error and recovery

```console
python3 tests/rhel/run.py --host "$RHEL_HOST" --ssh-key "$SSH_KEY" \
  --scenario "$RHEL_SCENARIO" --profile valkey --phase features \
  --feature-provider vllm --harness codex
```

This checks initial quota denial. Still test denial between tool calls, retry
behavior and a successful task after recovery, with no duplicated tool execution.

## Claude Code

### Model selection, discovery and limits

```console
praxis-harness claude --provider vllm --model "$MODEL" --print-config
praxis-harness claude --provider vllm --model "$MODEL"
```

Type `/model`, choose the configured Qwen entry, then run the file/test task.
Check context/output limits and thinking; repeat after resume and compaction.
Qwen uses simple mode and basic tools, so this does not qualify Claude's full
plugin, skill or subagent behavior.

For an enabled Anthropic provider, test native discovery separately:

```console
praxis-harness claude --provider anthropic --model claude-sonnet-4-6 \
  --gateway-model-discovery
```

Use an enabled model ID. Require a fresh gateway model-list request and its
entry in `/model`. Claude filters out Qwen IDs. A remote gateway with both
cloud providers exposes OpenAI's catalog on the shared route; use configured
Claude entries there.

### Quota error and recovery

```console
python3 tests/rhel/run.py --host "$RHEL_HOST" --ssh-key "$SSH_KEY" \
  --scenario "$RHEL_SCENARIO" --profile valkey --phase features \
  --feature-provider vllm --harness claude
```

Still test denial during a tool continuation, cancellation and successful
recovery without repeating an already completed tool.

## OpenCode

### Model selection and limits

```console
praxis-harness opencode --provider vllm --model "$MODEL" --print-config
praxis-harness opencode --provider vllm --model "$MODEL"
```

Type `/models`, choose `praxis/<model>`, then run the file/test task.
This is a configured entry, not gateway discovery. Check context/output limits
and thinking; repeat the task after resume and actual compaction.

### Quota error and recovery

```console
python3 tests/rhel/run.py --host "$RHEL_HOST" --ssh-key "$SSH_KEY" \
  --scenario "$RHEL_SCENARIO" --profile valkey --phase features \
  --feature-provider vllm --harness opencode
```

Still test retry timing, cancellation and successful recovery without duplicated
tools. For the sandboxed variant, repeat the model and task checks using the
[OpenShell OpenCode recipe](openshell-manual.md#2-qualify-actual-sandboxed-harnesses).

## OpenClaw / OpenShell

Test OpenClaw only through OpenShell. Its Praxis adapter is missing, so model
selection and quota behavior are **blocked**. Once available, run the same
selector → tool task → quota denial → recovery checks inside the sandbox.

Keep each sandbox harness separate: OpenCode's recipe is available; the Codex
Praxis adapter and Claude image/recipe remain missing. Ordinary-user sandbox
access is blocked by [#12](https://github.com/redhat-et/secure-single-server/issues/12).
[OpenShell probes](openshell-manual.md) test infrastructure; they do not qualify
a harness or its retry behavior.

## Shared gateway checks

As the **administrator on the gateway**:

```console
cd ~/secure-single-server-deploy
sudo scripts/common/quota-status
sudo scripts/common/quota-set --list
```

Status links to the list; the list prints commands for setting each quota.
Use the [quota administration guide](../quickstarts/common/token-quotas.md)
for list → preview → apply. Valkey retains usage across Praxis restarts;
process metrics restart, and `unknown` is not an empty allowance.

For repeatable API contracts without changing a VM, run on the workstation:

```console
python3 tests/mocked-provider.py --suite gateways --engine podman
```

Use `--engine docker` if needed. This covers both roles with memory and Valkey:
settlement/denial, shared Chat/Responses allowance, independent Messages quota,
window recovery, non-inference routes, authentication and backend failures.
Use `--feature-provider cloud` in the per-harness mock commands to test the
synthetic OpenAI/Anthropic routes.

The RHEL feature phase restores configuration and isolates its Valkey counters.
If interrupted before restoration, use the same selected mock VM/profile:

```console
python3 tests/rhel/run.py --host "$RHEL_HOST" --ssh-key "$SSH_KEY" \
  --scenario "$RHEL_SCENARIO" --profile valkey --phase features-restore
```

**RHEL API checks passed on both all-in-one CPU/GPU hosts:** real Qwen Chat
and Messages were admitted, then denied at a small quota. Denial survived
Praxis and Valkey restarts; raising capacity restored inference. Normal
capacities and namespaces were restored. This does not qualify CLI retry behavior.

Remaining qualification: concurrent reservations, expiry during real CPU/GPU
requests, active-stream cancellation, exact window boundaries, host reboot,
and harness retry/compaction behavior. Record role, CPU/GPU, provider/model,
backend, CLI/image versions and the observed result here; keep raw evidence private.
