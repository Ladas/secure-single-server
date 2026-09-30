# Why use this architecture?

This walkthrough explains why the pieces exist and then follows the validated
local path through them. It is written for an administrator deciding whether to
run coding agents for a small team on one managed RHEL server.

The short version is this: coding agents are useful because they can read a
workspace, run tools, and call a model. Those same powers create the operational
problems this repository tries to solve. The harness keeps the agent experience;
OpenShell constrains the tools; Praxis owns model access and shared usage; vLLM
serves an approved local model; bootc makes the host repeatable.

Every control below has a command or an explicit limitation attached to it. A
healthy service or a model saying that it ran a command is not accepted as proof.

## The problem it answers

Suppose several people ask to run Codex, OpenCode, or another coding harness on
a shared server. A direct approach is to create accounts, copy a provider key
into each harness, and let the agent use the shell. That can work on a trusted
laptop, but it leaves five operational questions unanswered:

| Question | What goes wrong without an architecture | Control used here |
| --- | --- | --- |
| Which files and tools can the agent touch? | A broad shell can read unrelated home directories, SSH material, or service state. | OpenShell policies declare writable sandbox paths, read-only system paths, and approved binaries. |
| Where can model traffic go? | An agent or tool can bypass the approved model and contact vLLM or a cloud provider directly. | The local OpenCode policy permits only `host.openshell.internal:8080`. |
| Who holds provider credentials? | Keys copied into harness homes are hard to rotate and easy to expose through prompts, logs, or tools. | Praxis owns credentials in gateway profiles; this local path has no cloud credential or fallback. |
| What happens when use grows? | One long-running task can consume a shared model; a cloud profile can also create a provider-bill surprise. | Praxis applies request and shared token limits before routing to the selected upstream. |
| Can the result be reproduced and recovered? | Hand-edited servers drift, and later updates are hard to reason about. | bootc packages pinned services and harness configuration into a reviewable OS image. |

The architecture does not try to make the harness smarter. It lets the harness
remain a normal coding agent while making its execution and model access
operable.

## Follow the validated path

This is the **OpenCode → Praxis → vLLM** path. It uses no cloud-provider
credential. Complete hardware, image, and OS prerequisites are in the
[vLLM guide](../../../bootc/VLLM.md); start with the OpenCode bootc variant.

### 1. Put the model on the host

After building and booting the OpenCode image, select CPU or single-L4 GPU mode:

```console
sudo sss-bootc vllm cpu
sudo sss-bootc vllm status
```

Wait until the model has loaded, then confirm that vLLM answers directly:

```console
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/v1/models
```

This direct request is a diagnostic. It proves the model is running, not that
the architecture is in effect. vLLM is deliberately loopback-only and is not the
endpoint given to the harness.

### 2. Put Praxis in the request path

```console
sudo sss-bootc inference vllm
sudo sss-bootc inference status
sudo sss-bootc inference check
```

`inference check` calls vLLM and then calls it through Praxis. A nonempty
completion through both paths verifies the administrator-selected upstream.
The [Praxis configuration](../../../configs/vllm/praxis.yaml) binds to
`127.0.0.1`, strips caller authorization headers, applies two requests per
second, and enforces a shared one-million-token rolling day with a 4,096-token
reservation per request.

Those limits are shared allowances, not per-user or USD budgets. See
[quota semantics](../common/token-quotas.md) before relying on them for cost
control.

### 3. Give the harness only the gateway

```console
sudo sss-bootc harness create --profile dev --name qwen-dev
sudo sss-bootc harness connect --name qwen-dev
```

OpenCode is configured to use the Praxis URL and a placeholder local API key.
The [OpenCode provider configuration](../../../configs/vllm/harness/harness-provider.json.in)
does not contain a provider secret. The
[sandbox network policy](../../../configs/vllm/harness/profiles/dev/policy.yaml)
allows the OpenCode and Node binaries to reach only the Praxis host alias.

That combination is the value of the architecture: the agent can still call a
model and use its tools, but it does not receive a cloud key, the vLLM port, or
the general network by default.

### 4. Run the evidence suite

From the host, run the automated end-to-end test against the sandbox:

```console
sudo bootc/test-inference qwen-dev
```

The test is intentionally stronger than a prompt-only demo. It checks that:

- the sandbox can list `Qwen/Qwen3-8B` through Praxis;
- direct connections to vLLM port 8000 are denied;
- direct connections to `api.openai.com` are denied;
- OpenShell audit records contain those denials;
- OpenCode returns a streamed completion;
- the model invokes the bash tool;
- a unique file is independently read back from `/sandbox`;
- no OpenCode JSON event is an error.

The final line should be:

```text
OpenCode → Praxis → vLLM and explicit bypass denial checks passed
```

The file check matters. An agent can describe a command that never ran; reading
the file from outside the model response is independent evidence that tool
execution happened.

### 5. Prove there is no silent cloud fallback

Optionally stop vLLM and call the gateway:

```console
sudo sss-bootc vllm disabled
curl --max-time 30 -i http://127.0.0.1:8080/v1/models
```

Praxis should fail with an upstream error, commonly HTTP 502 in the tested
deployment. That failure is the desired result: an unavailable local model does
not silently send the request to a paid cloud provider. Re-enable vLLM with
`sudo sss-bootc vllm cpu` or `sudo sss-bootc vllm gpu`.

The [runtime validation record](../../../bootc/VLLM-VALIDATION.md) contains the
exact images, hardware, output, and remaining limits from the AWS CPU and GPU
runs.

## Clean up

Deleting a sandbox destroys its work. Export anything you need first:

```console
sudo sss-bootc openshell sandbox delete qwen-dev
sudo sss-bootc vllm disabled
```

## Why each layer earns its place

| Layer | What it does | What it does not do |
| --- | --- | --- |
| Harness | Provides prompts, model selection, tool calling, and the developer experience. | Does not enforce host filesystem, network, or credential policy. |
| OpenShell | Runs the harness and tools under a declared filesystem and network policy and records allowed and denied operations. | Is not a multi-tenant authorization boundary in the current single-operator deployment. |
| Praxis | Makes the gateway the model path, strips client credentials, applies shared request and token limits, and chooses the approved upstream. | Does not yet provide per-user quotas, USD budgets, or a qualified usage dashboard. |
| vLLM | Serves the pinned local Qwen3-8B model on host loopback. | Is unauthenticated and therefore must not be published or exposed directly to harnesses. |
| bootc | Builds a reviewable, versioned RHEL host with pinned workload images and rollback. | Does not restore workspace data or application state on rollback. |

## Where the upstream ideas come from

- [OpenShell](https://github.com/NVIDIA/OpenShell) contributes the sandbox and
  policy model: agents can be useful while their filesystem, process, and
  network access remain constrained.
- [Praxis experimental](https://github.com/praxis-proxy/experimental) is the
  AI-gateway implementation this repository builds around. Its upstream demos
  also explore token budgets, provider routing, caller authentication, and
  trace-driven dashboards.
- [vLLM](https://github.com/vllm-project/vllm) supplies local model serving.
- The older [Praxis Ruby framework](https://github.com/praxis/praxis) is not the
  gateway used here; do not confuse it with the Rust experimental server in
  `praxis-proxy/experimental`.

This repository uses a narrower, pinned subset of those capabilities. It does
not import the upstream observability stack, per-user identity mapping, model
failover, or cloud-provider routing as qualified features.

## Know when not to use it

This architecture is a good fit when one administrator wants a reproducible
RHEL server for OpenCode tasks with an approved local model and explicit tool
boundaries. It is not yet the right answer if you require all of the following:

- per-user authentication and personal quotas;
- USD spend caps or billing chargeback;
- production multi-tenant isolation;
- Codex or OpenClaw through the local Qwen path;
- sustained-load or coding-quality guarantees.

Read the [integration matrix](../openshell-praxis/users.md) and
[trust model](../../../openshell/docs/threat-model.md) before extending the
validated path.

## Continue

- [Deploy the local Qwen3-8B example](../../../bootc/VLLM.md)
- [Read the OpenShell + Praxis integration guide](../openshell-praxis/README.md)
- [Understand quota semantics](../common/token-quotas.md)
- [Review the testing and acceptance guide](../../testing/README.md)
