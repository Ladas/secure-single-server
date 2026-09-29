# Debug native harnesses through Praxis and vLLM

The acceptance target is `harness → Praxis → real vLLM → Qwen` on CPU and GPU,
including streamed tools, continuation and quota accounting. Direct-backend
calls are diagnostic controls. They do not replace acceptance through Praxis.
See the [compatibility matrix](compatibility.md) for established results.

## API paths

vLLM serves several API shapes from the same model process:

| Client | API | Praxis route | Private vLLM endpoint |
| --- | --- | --- | --- |
| Codex | OpenAI Responses | `/vllm/v1/responses` | `/v1/responses` |
| OpenCode | OpenAI Chat Completions | `/vllm/v1/chat/completions` | `/v1/chat/completions` |
| Claude Code | Anthropic Messages | `/vllm/v1/messages` | `/v1/messages` |

These are vLLM implementations of compatible APIs, not requests to OpenAI or
Anthropic. CPU and GPU expose the same API family but use separate image pins.
The current Praxis configuration strips `/vllm` and forwards the native API;
it does not enable translation filters. Backend port 8000 remains private.
See vLLM's [API documentation](https://docs.vllm.ai/en/v0.30.0/serving/online_serving/openai_compatible_server/)
and [Claude integration](https://docs.vllm.ai/en/v0.30.0/serving/integrations/claude_code/).

## 1. Separate hardware from gateway configuration

| Test VMs | Comparison |
| --- | --- |
| `all-in-one-cpu` and `all-in-one-gpu` | CPU/GPU with the same local gateway scenario; qualify these first |
| `remote-gateway-cpu` and `remote-gateway-gpu` | Repeat through HTTPS/JWT after all-in-one qualification |

Use the [AWS deployment blocks](aws.md#3-deploy-the-vms-you-need). New installs
use thinking enabled; the prior non-thinking results remain a separate baseline.
Do not disable thinking to claim acceptance of the requested configuration.

Keep model revision, chat template, parser, thinking mode, context length,
sampling and CLI versions fixed. Record CPU and GPU image digests separately;
a GPU result never qualifies CPU. CPU deadlines must allow slower inference;
record time to first token and total time separately from protocol failures.

## 2. Make failures reproducible

Extend the test tooling before changing pins:

1. Save per-run scenario, inference mode, instance type, actual Praxis/vLLM
   image IDs and source labels, vLLM/Python dependency versions, model revision,
   template hash, server arguments, CLI versions and gateway config hash.
   Real-test result JSON now records deployed image references/IDs, source
   labels, backend package versions, model/parser/thinking settings, kernel
   and template/gateway hashes. Keep the workstation AWS journal for instance
   type and the CLI version output beside this record.
2. Capture a synthetic native CLI request and its response stream at the client
   and backend boundaries. Remove JWT/provider credentials. Record status,
   ordered SSE events, tool IDs/arguments, terminal event, usage and traceback.
3. Replay that same request directly against the private backend and through
   Praxis on each backend. Normalize only the route prefix and expected
   credential handling. Use the backend network namespace or a private test
   client; publish no inference port.
4. Reduce each failure to a small JSON fixture: basic text, one streamed tool,
   split argument deltas, tool-result continuation, then the full CLI request.
   Add the reproducer as a regression before fixing its responsible component.

Thinking-enabled controls now cover both backends: captured Claude requests on
CPU/GPU, a captured GPU Codex stream/continuation and a reduced CPU reasoning
continuation. Full CPU Codex stream replay remains useful for confirming the
argument-aggregation defect there. Compare captured requests, not only similar
task descriptions.

## 3. Test candidate fixes one change at a time

| Candidate | Keep fixed | Question answered |
| --- | --- | --- |
| Current Praxis and current native vLLM APIs | All pins and config | Does the reduced fixture reproduce the recorded failure? |
| Corrected launch/client settings | Images, model and API path | Is the problem in this repository's setup, parser/template selection, URL or CLI options? |
| PR #40 Praxis image, same native routes | vLLM CPU/GPU pins and all model/client settings | Does the Praxis version change native forwarding behavior? |
| PR #40 Praxis with explicit API translation to Chat Completions | Same vLLM/model/CLI pins | Can Praxis provide the client API using the working backend Chat API? |
| A vLLM candidate release or narrow patch | Praxis image and native routes | Does the backend fix work directly and then through Praxis on both CPU/GPU? |
| An older compatible CLI pin as a diagnostic control | Images and server settings | Which client request change introduced the incompatibility? |

Do not change Praxis, vLLM and the CLI simultaneously. Retain baseline digests
and configuration for rollback. The SSH runner accepts `--vllm-image` only
with `real-setup` and requires an immutable digest. The Praxis installer accepts
`--praxis-image IMAGE@sha256:DIGEST`; that override is not yet exposed by the SSH
runner.

### Qwen launcher settings

The server uses `enable_thinking=true`, `qwen3` reasoning parsing and `hermes`
tool parsing. The launcher adds Qwen-specific settings:

- OpenCode: declare reasoning support and preserve the `reasoning` field on
  tool continuations; emit reasoning events in noninteractive test logs.
- Codex: advertise the installed 16k context, compact before exhausting it and
  display the raw reasoning events returned by Qwen. The pinned CLI has no
  separate maximum-output-token option; the server bounds remaining context.
- Claude: use 16k context and 4096 output tokens, including thinking. Its
  unknown-model default requested 32,000 output tokens and was rejected by the
  16k backend. This is a launcher fix, independent of the system-role defect.

Cloud models keep their own settings. Thinking consumes the output budget;
an exhausted budget without final text is a failure. These lab limits do not
provide cloud-sized context or identical reasoning controls. Follow Qwen's
[thinking-mode sampling guidance](https://huggingface.co/Qwen/Qwen3-8B#best-practices);
do not force greedy decoding to make runs appear deterministic.
The runner allows CPU tasks more time without changing these model settings;
see the [measured limits](compatibility.md#cpugpu-limits-and-measured-performance).

### CPU Codex task failures

The 0.30 backend accepts the native API, but the CPU Codex task remains failed:

- Original client defaults: no successful tool task before the 30-minute timeout.
- Corrected 16k context and compaction: valid shell calls repeatedly requested
  `require_escalated`, which the noninteractive policy refused.
- Additional permission guidance: calls used `use_default`, but Qwen called
  `apply_patch` even though the request did not advertise that tool, then
  repeatedly ran a zero-test suite without creating the required files.

The two diagnostic loops were stopped with evidence retained. The extra guidance
is not shipped in the launcher because it did not qualify the task. GPU Codex
passed three runs, but this difference does not prove a CPU implementation defect.

Next, replay the same captured request on both backends, recording rendered
tools, sampling settings and output. Compare model decisions separately from
SSE parsing. Test one client/model-instruction change at a time; require generated
files, nonempty tests and independent checks. Keep the enforced sandbox and
thinking enabled. Use the passing CPU OpenCode/Claude paths for manual testing
while Codex remains unqualified.

### Compare a vLLM candidate

The defaults are the tested v0.30 CPU/GPU digests. To compare another version,
obtain a published immutable image for the selected backend (`vllm-openai-cpu`
or `vllm-openai`, linux/amd64). Record its release/source revision first:

```console
printf 'Candidate image (NAME@sha256:DIGEST) for %s: ' "$RHEL_INFERENCE"
IFS= read -r CANDIDATE_VLLM_IMAGE &&
python3 tests/rhel/run.py --host "$RHEL_HOST" --ssh-key "$SSH_KEY" \
  --scenario "$RHEL_SCENARIO" --phase real-setup --inference "$RHEL_INFERENCE" \
  --vllm-image "$CANDIDATE_VLLM_IMAGE" &&
python3 tests/rhel/run.py --host "$RHEL_HOST" --ssh-key "$SSH_KEY" \
  --scenario "$RHEL_SCENARIO" --phase real-test
```

Run comparisons before adding real cloud credentials. Model, thinking mode,
Praxis and CLI pins stay fixed. To restore the repository's baseline image,
repeat `real-setup` without `--vllm-image`, then rerun `real-test`.

### Praxis image and translation

[Experimental PR #40](https://github.com/praxis-proxy/experimental/pull/40)
merged as `019aa849a219e5c881d69e4a40a1fc190bd6c404`. It updates AI to v0.4.1
at `b9d6016764888e02dc049ec088496b10b7e886c1` with `full` features; its PR head
was `84e1da73696fac22d21cd8f787543badda64207c`. Obtain a native amd64 build
or a published digest whose source revision includes that change. A successful
PR container job is not publication, and merge is not runtime qualification.
Verify the publication job and image labels before selecting a candidate;
do not assume a moving Quay/GHCR tag contains the expected source.

First compare the image with native routes unchanged. Then test separate,
explicit translation configurations:

- Codex: client Responses → Praxis `responses_to_chat_completions` → vLLM Chat
  Completions, with Responses SSE translated back to the client. Start from the
  [v0.4.1 example](https://github.com/praxis-proxy/ai/blob/b9d6016764888e02dc049ec088496b10b7e886c1/examples/configs/openai/responses/responses-to-chat-completions.yaml).
  Verify stream-filter order, deadlines and terminal usage. The v0.4.1 vLLM
  reasoning dialect rejects streaming. This is a translation gap to qualify or
  fix; preserve model thinking and verify reasoning events instead of silently
  disabling reasoning to obtain a passing result.
  If the CLI uses stored continuation, configure an image-supported response
  store with appropriate ownership; do not silently discard history or copy
  the example's single-tenant SQLite assumptions into a shared gateway.
- Claude: client Messages → Praxis `anthropic_messages_to_chat_completions` and
  `anthropic_messages_to_chat_completions_stream` → vLLM Chat Completions. Use the
  [matching example](https://github.com/praxis-proxy/ai/blob/b9d6016764888e02dc049ec088496b10b7e886c1/examples/configs/anthropic/messages-to-openai.yaml).
  Explicitly test the CLI's system-role extension; translation is a candidate,
  not proof that this input is accepted or semantically preserved.

These configurations are planned experiments, not installed modes. A newer
image alone cannot enable filters absent from the gateway configuration.
Check usage and quotas across translation boundaries: PR #40 does not include
[AI #1231](https://github.com/praxis-proxy/ai/pull/1231), which concerns forcing
terminal usage for streaming Chat clients that omit `include_usage`.

### vLLM candidates

Static review of vLLM **v0.19.0** identifies a concrete Codex failure candidate:
[Hermes emits a tool-name delta before its arguments](https://github.com/vllm-project/vllm/blob/v0.19.0/vllm/tool_parsers/hermes_tool_parser.py),
while [Responses event construction](https://github.com/vllm-project/vllm/blob/v0.19.0/vllm/entrypoints/openai/responses/serving.py)
passes that first delta's nullable arguments to `ResponseFunctionToolCallItem`.
This matches the recorded `arguments=None` traceback. It is a source-level
lead, not a tested patch. Reduce it to a regression, then check accumulated
arguments, split deltas, reasoning, continuation and terminal completion.
Changing thinking mode may change which delta arrives first; that alone would
not establish a complete streaming fix.

With thinking enabled, CPU/GPU native Codex runs reach a continuation
that v0.19.0 rejects because its reasoning item lacks `id`. A reduced private
backend replay reproduces that rejection. This matches
[vLLM #33089](https://github.com/vllm-project/vllm/issues/33089);
[v0.30.0's input preprocessing](https://github.com/vllm-project/vllm/blob/v0.30.0/vllm/entrypoints/openai/responses/protocol.py)
generates missing reasoning IDs.

The GPU's captured first request also reproduces malformed arguments directly
against vLLM: multiple tool calls' JSON argument objects are concatenated into
one completed call. In v0.19.0, `serving.py` joins argument deltas from all prior
delta messages without selecting the tool index. This matches
[vLLM #39426](https://github.com/vllm-project/vllm/issues/39426). Fixing only
continuation validation cannot qualify tool execution; compare each call's
deltas, final arguments, ID and result independently.

The v0.30 GPU backend completes native Codex tasks, but its captured stream
still changes tool `id` and `call_id` between `response.output_item.done` and
`response.completed`. Per-tool deltas and arguments match. Its
[final response builder](https://github.com/vllm-project/vllm/blob/v0.30.0/vllm/entrypoints/openai/responses/serving.py)
reparses the full output instead of reusing streamed items (an existing TODO).
Private replay of the same request reproduced this without Praxis. Add a
regression that requires stable IDs in the completed response and reuse the
accumulated stream objects.
[vLLM #44676](https://github.com/vllm-project/vllm/issues/44676) records similar
ID drift as a secondary finding; its main thinking-budget issue concerns a
different model/configuration. Do not claim that all OpenAI Responses semantics
are qualified because Codex's smoke task passes.

For Claude, the error matches [vLLM #44000](https://github.com/vllm-project/vllm/issues/44000).
[PR #44283](https://github.com/vllm-project/vllm/pull/44283) adds system-role
acceptance; [PR #44602](https://github.com/vllm-project/vllm/pull/44602) preserves
inline placement. [#48874](https://github.com/vllm-project/vllm/issues/48874)
reports later prompt/tool problems. Identify a release containing the needed
changes with both CPU/GPU builds, then test prompt semantics and real tool
execution. HTTP 200 alone is insufficient.

For source investigation, clone upstream and reproduce against the pinned tag
before comparing a candidate revision:

```console
git clone --depth 1 --branch v0.19.0 https://github.com/vllm-project/vllm.git ../vllm
```

If the checkout already exists, inspect its status and revision instead of
cloning over it. Follow its development instructions before running tests.

## 4. Put the fix in the owning repository

| Finding | Change location |
| --- | --- |
| Wrong URL, CLI option, parser/template, startup setting or filter wiring | `secure-single-server` scripts/configuration and regression tests |
| Failure introduced by Praxis forwarding or translation with a valid backend control | `praxis-proxy/ai` filter PR, or core `praxis` if transport is responsible; then update Experimental and the deployment digest |
| AI fix already exists in v0.4.1 | Qualify PR #40's image, publish through the image workflow, and update the deployment pin/configuration |
| Direct backend failure fixed by vLLM code/version | Upstream vLLM issue/PR or verified release; update both backend pins with separate results |
| Native tool transport succeeds but generated work is wrong | Model/prompt evaluation; preserve the failure without misclassifying it as a proxy defect |

## 5. Add sandbox execution without losing the native baseline

Use the same all-in-one VM and personal login after the native baseline passes.
The administrator installs OpenShell under its separate service account; the
user registers the loopback gateway and runs sandbox clients without sudo.
The [manual commands](openshell-manual.md) expose this split. Keep OpenShell
explicit in the full test preset: it adds a management API that trusts local
users, so installation alone does not establish isolated personal sandboxes.

1. Repeat direct harness checks after installing the addon. Preserve the
   working Praxis/vLLM configuration, secrets and provider routes.
2. Run actual sandboxed CLI file/test tasks against mocked Qwen, OpenAI and
   Anthropic through Praxis. The current optional phase's API/policy probe is
   insufficient. Check credential replacement, streaming, tool continuation
   and final usage, with positive and explicit network-denial controls.
3. Start with OpenCode. Reuse bootc's successful CPU/GPU qualification method,
   while testing the mutable host's private vLLM network and `/vllm/v1` route.
   Route rendering now supports this prefix; runtime acceptance is still due.
4. Implement and test the missing Codex/OpenClaw Praxis config adapters;
   retain their rejection guards until they work. Add a pinned Claude sandbox
   image/recipe before testing it. OpenClaw is sandbox-first for this workflow;
   its standalone image check does not qualify its model/tool integration.
5. Repeat real Qwen on CPU/GPU, then optional real cloud providers. Run CLI/tool
   checks as the ordinary host user or sandbox user, never as the administrator.
   Record native and sandbox results separately, including failed combinations.

Require Praxis-only model routing, no cloud credentials in the user/sandbox,
explicit denial of direct backend/provider access, and independently checked
generated files. A separate user's sandbox ownership, private workspace and
logout/reboot retention need dedicated acceptance; do not infer them from the
current trusted-local management API.

Retain the merged per-sandbox CPU/memory limits and inspect their actual Podman
runtime values. Adapt `bootc/test-kernel`'s probe for the mutable service-owner
environment to record kernel, Landlock and seccomp behavior. Test dev-server
socket operations separately from inference; neither build checks nor prior
OpenCode inference establish this result on the current VMs.

## 6. Acceptance before declaring support

Require the full native CLI file/test task through Praxis on CPU and GPU:
streamed tool arguments, matching tool results, continuation, complete terminal
response and usage, independent test execution, and appropriate quota charging.
Repeat with fresh projects and require three consecutive passes per combination.
Recheck TLS/JWT, unknown-model denial, unavailable backend without cloud fallback,
restart/reboot, and existing cloud mock regressions.

Record native-forwarding and translated modes separately in the compatibility
matrix, including exact pins. Only passing deployed combinations become the
recommended manual path. Real OpenAI/Anthropic calls remain a separate manual
gate after the mock checks; no real credentials are needed for this investigation.
