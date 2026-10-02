# Harness feature testing

Track feature support and testing here. Keep provider/backend tool-task results
in [compatibility.md](compatibility.md).

| Feature | Codex | Claude Code | OpenCode | OpenClaw / OpenShell |
| --- | --- | --- | --- | --- |
| Model selection | Unified configured catalog | Unified configured picker | Both unified catalogs | Blocked: missing Praxis adapter |
| Catalog refresh | `praxis-harness-config` | Same; native discovery disabled | Same | Not qualified |
| Short-history model switching | Passed with Responses adapter [details below](#model-switching-and-reasoning) | Messages round trips passed | Responses/Messages round trips passed with adapter | Not qualified |
| Thinking and context limits | Per-model context; compaction pending | Unknown-model context override; known Claude windows differ | Per-model context/output; compaction pending | Not qualified |
| Tool approvals | Native controls | Manual for Qwen; auto classifier blocked | Native controls | Depends on sandbox/adapter |
| Inspect/change token quota | Praxis administrator commands | Same | Same | Same gateway controls; adapter pending |
| CLI quota error and recovery | Mock test available; RHEL pending | Mock test available; RHEL pending | Mock test available; RHEL pending | Blocked |
| Shared vLLM allowance | Shared Valkey budget across Responses, Chat and Messages; API-tested | Same | Same | Adapter pending |
| Quota persistence | Via Praxis/Valkey | Via Praxis/Valkey | Via Praxis/Valkey | Adapter pending |

“Configured” describes available configuration, not a new interactive test pass.

**Contents:** [Codex](#codex) · [Claude Code](#claude-code) ·
[OpenCode](#opencode) · [OpenClaw / OpenShell](#openclaw--openshell) ·
[Shared gateway checks](#shared-gateway-checks)

For the **unified all-in-one** workflow, complete [provider setup](../quickstarts/common/providers.md)
and [ordinary-user configuration](../quickstarts/all-in-one/users.md), then run
the native commands below in a project directory. Refresh catalogs before testing.
For each selected model, run the [file/test task](harnesses.md#acceptance-task)
and verify the actual tool result; a menu entry is insufficient.

Remote gateways retain [separate client setup](harnesses.md#remote-gateway-client)
and per-provider launcher routes. Unified catalogs and the adapter below are not
qualified for remote gateways or OpenShell.

The quota commands below run on the **workstation**, after selecting a
[disposable mock VM](rhel-smoke.md). They use Valkey; use `--profile memory`
only on a VM prepared with that profile. The feature phase refuses real-provider
installations, including the manual Qwen CPU/GPU hosts.

## Codex

### Model selection and limits

```console
codex --profile praxis
```

Type `/model`, select a configured alias, and run the file/test task. Repeat
with another provider and back in the same session, then after resume.
Use the [Responses adapter](#responses-history-experiment) for cloud → Qwen
returns; the normal listener still rejects encrypted reasoning. Verify
compaction separately; short-history passes do not qualify it.

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
claude-code
```

Type `/model`, select Qwen or an enabled Messages alias, and run the file/test
task. Switch to each other model and back; repeat after resume. This configured
picker includes Qwen; native discovery is disabled because it filters out
non-Claude IDs. The Messages round trips below passed without the adapter.

Simple mode and basic tools do not qualify full plugin, skill or subagent
behavior. Keep Manual tool approval mode: the auto classifier is blocked with
Qwen. Verify a shell command asks for approval and runs after approval.
Compaction and switching a large Claude history into Qwen's 32K window remain
unqualified.

### Quota error and recovery

```console
python3 tests/rhel/run.py --host "$RHEL_HOST" --ssh-key "$SSH_KEY" \
  --scenario "$RHEL_SCENARIO" --profile valkey --phase features \
  --feature-provider vllm --harness claude-code
```

Still test denial during a tool continuation, cancellation and successful
recovery without repeating an already completed tool.

## OpenCode

### Model selection and limits

```console
opencode
```

Type `/models`, choose `praxis-openai/<alias>` or `praxis-messages/<alias>`,
and run the file/test task. Both can be selected in one conversation; an
initial `--model` does not lock the API. Switch in both directions and resume.
On the normal gateway, use Qwen Messages for cloud → Qwen returns; qualify
Qwen Responses with the [adapter](#responses-history-experiment).

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

### Model switching and reasoning

Recorded on the all-in-one GPU: Qwen3.8-27B INT4 / vLLM 0.30.0 (32K context,
8K output budget), Praxis core 0.7.0 / AI 0.4.1, Codex 0.157.1,
Claude Code 2.1.283 and OpenCode 1.18.32. CPU, remote and OpenShell switching
are not qualified. These are resumed native CLI tasks, not interactive menu captures.

| Round trip in one conversation | Codex | Claude Code | OpenCode |
| --- | --- | --- | --- |
| Local Qwen Responses ↔ each configured direct/custom GPT Mini, Luna and Sol | Passed with adapter [1, 2] | Different API | Passed with adapter [1–3] |
| Direct OpenAI ↔ custom-provider GPT, including forward/reverse Mini → Luna → Sol chain | Passed | Different API | Passed |
| Messages: every pair of Qwen, hosted Flash, Sonnet and Opus, both ways | Different API | Passed | Passed |
| Qwen Responses ↔ each of those Messages entries | Different API | Different API | Passed with adapter [1–3] |
| Direct/custom GPT Mini Responses ↔ each Messages entry | Different API | Different API | Passed |
| GPT Luna/Sol Responses ↔ each Messages entry | Different API | Different API | Not run |
| Long history, actual compaction and switching into a smaller context | Not run [4] | Not run | Not run [4] |

Each turn recalled a conversation-only marker and executed unit tests. The
adapter runs covered 36 turns / 32 switches. Preserve private result JSON and
CLI logs with your test record; do not commit conversations or credentials.

1. **Installed Praxis filter:** unified mode with `--vllm-reasoning hide` adds
   `include_reasoning: false` only to local vLLM Responses requests. Qwen still
   thinks; its plaintext reasoning is not returned for later cloud replay.
2. **Experimental adapter:** when targeting the local Qwen alias, omit whole
   encrypted reasoning input items that vLLM cannot decode. Plain messages,
   tool calls/results and saved session files remain unchanged. Cloud requests
   pass through unchanged. This is not encrypted-reasoning interoperability.
3. **Experimental adapter:** add missing `type: "message"` to assistant
   `output_text` messages. This fixes the OpenCode → vLLM input-schema rejection.
4. **Still blocked:** opaque compaction and provider-local references are
   rejected, not discarded. Short sessions do not qualify long-history quality,
   automatic compaction or fitting a cloud transcript into Qwen's context.

The default `:8080` listener has only fix [1]. Returning through Responses
still fails there; [2–3] require the adapter. A hosted Flash model tested through
the custom provider returned upstream `404 model_not_found` on Responses;
its Messages route passed. Confirm native API access before adding an alias.

### Responses history experiment

Keep the adapter out of production startup. From the workstation checkout,
copy only the public test script to the selected administrator login:

```console
scp -o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY" \
  tests/rhel/responses_compat.py "$RHEL_HOST:~/responses_compat.py" &&
ssh -o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY" "$RHEL_HOST" \
  'sudo install -D -m 0644 ~/responses_compat.py /usr/local/share/praxis/experiments/responses_compat.py'
```

As the **ordinary user on the all-in-one VM**, start the temporary service.
Use the exact configured local alias (8B: `vllm/qwen3-8b`):

```console
systemctl --user is-active --quiet praxis-responses-compat ||
  systemd-run --user --unit=praxis-responses-compat --collect \
  /usr/bin/python3 /usr/local/share/praxis/experiments/responses_compat.py \
  --port 18180 --upstream-port 8080 --model vllm/qwen3.8-27b-int4
curl --fail --silent --show-error --connect-timeout 3 --max-time 5 \
  http://127.0.0.1:18180/v1/models | python3 -m json.tool
```

**Stop if the catalog check fails.** Every model in the overridden harness,
including cloud models, depends on the adapter running. Inspect it with
`systemctl --user status praxis-responses-compat --no-pager`.
The path is harness → adapter `18180` → Praxis `8080` → upstream; this is
neither a new Praxis listener nor a new filter chain. Messages stays on `8081`.

From a project directory, choose a harness:

```console
codex --profile praxis \
  -c 'model_providers.praxis.base_url="http://127.0.0.1:18180/v1"'
```

Append `resume` to choose an existing Codex session. For OpenCode:

```console
OPENCODE_CONFIG_CONTENT='{"provider":{"praxis-openai":{"options":{"baseURL":"http://127.0.0.1:18180/v1"}}}}' \
  opencode --model praxis-openai/vllm/qwen3.8-27b-int4
```

Run the task in both switch directions. Restart without the override to return
to normal routing, then stop the temporary adapter:

```console
systemctl --user stop praxis-responses-compat
```

<details>
<summary>Automated round-trip check</summary>

From the workstation, copy the test bundle to the administrator account:

```console
ssh -o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY" "$RHEL_HOST" \
  'install -d -m 0700 ~/secure-single-server-deploy/tests' &&
scp -pr -o IdentitiesOnly=yes -o ForwardAgent=no -i "$SSH_KEY" \
  tests/common tests/rhel "$RHEL_HOST:~/secure-single-server-deploy/tests/"
```

Then in an administrator SSH session, use enabled aliases. Repeat
`--cloud-model` and `--messages-model` to cover additional choices:

```console
cd ~/secure-single-server-deploy
printf 'Enabled cloud Responses alias: '
IFS= read -r CLOUD_MODEL
sudo python3 tests/rhel/responses-switching.py --user praxis-user \
  --local-model vllm/qwen3.8-27b-int4 --cloud-model "$CLOUD_MODEL"
```

Stop the interactive adapter first so port 18180 is free. This runner starts
and stops its own adapter, runs CLIs as the ordinary user, and stores private
results under that user's `~/rhel-smoke/responses-compat-*/`. It makes real
provider calls and returns nonzero for failed recall or tool execution.

</details>

### Quota administration and API checks

As the **administrator on the gateway**:

```console
cd ~/secure-single-server-deploy
sudo scripts/common/quota-status
sudo scripts/common/quota-set --list
```

Status links to the list; the list prints commands for setting each quota.
Use the [quota administration guide](../quickstarts/common/token-quotas.md)
for list → preview → apply. Valkey retains usage across Praxis restarts;
the status command reads its current ledger separately from process counters.

For repeatable API contracts without changing a VM, run on the workstation:

```console
python3 tests/mocked-provider.py --suite gateways --engine podman
```

Use `--engine docker` if needed. This covers both roles with memory and Valkey:
settlement/denial, separate API quotas and the opt-in shared vLLM Valkey budget,
window recovery, non-inference routes, authentication and backend failures.
The extended provider checks cover migration without losing charges, cross-API
denial/recovery, and additional compatible providers with independent quotas.
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
The status helper also read both hosts' persisted quota balances without restarting services.
The GPU now uses one shared vLLM budget: migration preserved existing charges,
and real Chat/Messages requests added their reported usage to that same ledger.
Native-file Codex catalogs passed `model/list`; OpenCode passed `opencode models`.
Real cloud switching is recorded above; interactive selector captures remain separate.

Remaining qualification: concurrent reservations, expiry during real CPU/GPU
requests, active-stream cancellation, exact window boundaries, host reboot,
and harness retry/compaction behavior. Record role, CPU/GPU, provider/model,
backend, CLI/image versions and the observed result here; keep raw evidence private.
