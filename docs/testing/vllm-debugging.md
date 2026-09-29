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
See vLLM's [API documentation](https://docs.vllm.ai/en/v0.19.0/serving/openai_compatible_server/#supported-apis)
and [Claude integration](https://docs.vllm.ai/en/v0.19.0/serving/integrations/claude_code/).

## 1. Separate hardware from gateway configuration

| Test VM | Purpose |
| --- | --- |
| Existing GPU all-in-one | GPU baseline, local Praxis listeners |
| Existing CPU remote-gateway | CPU baseline, HTTPS/JWT gateway |
| Additional CPU all-in-one | Compare CPU/GPU with the same scenario; compare local/remote scenarios on the same CPU preset |

The additional CPU VM improves isolation but is not required to start direct
CPU/GPU reproductions on the existing hosts. A GPU remote-gateway can complete
the four-way matrix later if a scenario-specific failure remains.
[Additional-VM commands](aws-operations.md#deploy-additional-variants-of-a-scenario)
reuse the existing helper without changing either original VM's variables.

Keep model revision, chat template, parser, thinking mode, context length,
sampling and CLI versions fixed. Record CPU and GPU image digests separately;
a GPU result never qualifies CPU. CPU deadlines must allow slower inference;
record time to first token and total time separately from protocol failures.

## 2. Make failures reproducible

Extend the test tooling before changing pins:

1. Save per-run scenario, inference mode, instance type, actual Praxis/vLLM
   image IDs and source labels, vLLM/Python dependency versions, model revision,
   template hash, server arguments, CLI versions and gateway config hash.
   Existing host logs and bundle hashes are useful but do not yet provide this
   complete structured record.
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

The earlier direct reproductions were on GPU. Repeat them on CPU before
attributing a common source defect to both builds. Compare captured requests,
not only similar task descriptions.

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
and configuration for rollback. The current installer supports
`--praxis-image IMAGE@sha256:DIGEST`; the SSH runner does not yet expose that
option. Add tested candidate overrides and provenance before automating the
image comparison. vLLM candidates likewise need explicit CPU/GPU digest
selection, preserving the default pins until qualification passes.

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
  Verify stream-filter order, deadlines and terminal usage. Keep reasoning
  dialect disabled initially: v0.4.1's vLLM reasoning dialect rejects streaming.
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

For Codex, reduce the `ResponseFunctionToolCallItem(arguments=None)` failure
and inspect vLLM's Responses event construction and pinned OpenAI/Pydantic
schemas. Test fragmented arguments, one/parallel calls and terminal completion.
Do not replace missing arguments with an arbitrary value just to avoid a crash.

For Claude, our validation error matches the failure reported in
[vLLM #44000](https://github.com/vllm-project/vllm/issues/44000).
[PR #44283](https://github.com/vllm-project/vllm/pull/44283) adds system-role
acceptance, but [#48874](https://github.com/vllm-project/vllm/issues/48874)
reports subsequent problems with message placement. Identify a release that
contains the required fixes and has both CPU/GPU builds; then verify prompt
semantics and tool execution. Merely turning HTTP 400 into HTTP 200 is insufficient.

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
