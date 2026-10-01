# Optional Qwen3-8B inference

This guide is the implementation half of the story. If you want to understand
why the layers are separated before enabling them, start with the
[architecture value walkthrough](../docs/quickstarts/architecture-walkthrough/README.md).

The supported topology runs `Qwen/Qwen3-8B` in vLLM on a separate server. The
bootc single server keeps only OpenShell, Praxis, and the harness, preserving
the **OpenCode → Praxis → vLLM** boundary without coupling inference resources
to the single-server host. The older co-located bootc profile remains available
for compatibility but is deprecated for new deployments.

The configured request path is **OpenCode → Praxis → vLLM**. Local vLLM
serving and the host Praxis route can be checked independently. The sandbox
path uses the trusted host mapping in OpenShell v0.1.2-rhaiv.0. Codex and OpenClaw
local adapters are not enabled.

## Host requirements

- Published OS images: `quay.io/redhat-et/secure-single-server-vllm-cpu:v0.1`
  and `quay.io/redhat-et/secure-single-server-vllm-gpu:v0.1`.
- Separate CPU vLLM server: x86_64 with AVX-512, at least 32 GB RAM, and 64
  GiB recommended. This is a starting resource budget, not a throughput
  guarantee. The CPU profile uses BF16, a 4 GiB KV cache, and no explicit CPU
  affinity/NUMA binding. Boot `vllm-cpu`; it omits NVIDIA drivers and the
  Container Toolkit.
- GPU: exactly one NVIDIA L4, a compatible NVIDIA host driver, and
  `nvidia-ctk` installed in the bootc OS image. The reconciler regenerates CDI
  at boot. `vllm-gpu` includes the NVIDIA 580 open driver and Container
  Toolkit. The build compiles the module for the kernel inside the image and
  fails if that kernel cannot be supported. Rebuild after kernel updates.
  Secure Boot with a custom signing key is not configured.
- Persistent disk on the vLLM server: allow space for roughly 16 GB of model
  weights, workload images, and caches. Budget at least 100 GiB for CPU or
  200 GiB for GPU demonstrations and check free space first.
- First startup needs access to Docker Hub and Hugging Face download endpoints.
  No Hugging Face token is required for this public model.

Both profiles use BF16, a 16,384-token context, one concurrent sequence, eager
execution, and tensor parallel size 1. GPU memory utilization is limited to
90%. OpenCode reserves at most 2,048 output tokens within that context. Thinking is
disabled by default for predictable demo latency; callers can explicitly
set `chat_template_kwargs.enable_thinking` to true.

## Separate AWS server and endpoint discovery

Use the [AWS deployment guide](../docs/testing/aws.md#separate-vllm-server)
to launch a dedicated tagged vLLM VM, grant TCP 8000 only to the single
server's security group, and discover its private address. After both VMs are
in the same VPC, the administrator-side helper prints an `RFC1918_IP:PORT` endpoint;
no AWS credential or instance profile is placed on the single server.

```console
source scripts/aws/session.sh
VLLM_INFO="$(aws_test_vllm_endpoint vllm-server-gpu)" \
  || printf 'Endpoint discovery failed; inspect the vLLM VM.\n'
VLLM_ENDPOINT="$(printf '%s' "${VLLM_INFO:-}" | jq -er '.VllmEndpoint')" \
  || printf 'Endpoint JSON was invalid.\n'
printf 'Private vLLM endpoint: %s\n' "${VLLM_ENDPOINT:-unknown}"
```

On the dedicated server, boot `vllm-cpu` on a CPU instance or `vllm-gpu` on
the L4 instance. Alternatively, use the mutable RHEL vLLM installer with
`--remote PRIVATE_IP` so port 8000 binds only to its private AWS address. On the
booted single server, configure Praxis without changing the OpenShell harness
policy:

```console
sudo sss-bootc inference remote-vllm "$VLLM_ENDPOINT"
sudo sss-bootc inference status
sudo sss-bootc inference check
```

Praxis continues listening only on `127.0.0.1:8080`; the sandbox still reaches
`host.openshell.internal:8080` and has no direct vLLM or cloud-provider egress.
If the remote server stops, Praxis returns an upstream error rather than
falling back to a cloud provider.

## Build and boot a dedicated vLLM image

Build and boot the updated OS using the [bootc instructions](README.md).
The dedicated `vllm-cpu` and `vllm-gpu` targets build directly from RHEL bootc
and exclude Praxis and OpenShell. The CPU target omits NVIDIA components; the
GPU target includes the NVIDIA 580 open driver and Container Toolkit:

```console
sudo env RHEL_BOOTC_IMAGE="$RHEL_BOOTC_IMAGE" AWS_RHUI_REGION=us-east-1 \
  bootc/build vllm-cpu localhost/secure-single-server

sudo env RHEL_BOOTC_IMAGE="$RHEL_BOOTC_IMAGE" AWS_RHUI_REGION=us-east-1 \
  bootc/build vllm-gpu localhost/secure-single-server
```

GPU drivers are OS components; vLLM and model weights remain separate workload
containers and persistent data. On the booted host, select the mode matching
the image. Mismatched selections are rejected before starting a container:

```console
sudo sss-vllm select cpu
# On the vllm-gpu image booted on the prepared single-L4 host:
sudo sss-vllm select gpu
sudo sss-vllm status
sudo journalctl -u secure-single-server-vllm.service -b
sudo journalctl _SYSTEMD_USER_UNIT=vllm.service -f
```

The first command pulls the selected pinned image. Model download/loading
continues after systemd starts the container; an active unit alone does not
prove inference readiness. Retry the health request while loading, inspecting
logs if startup fails:

```console
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/v1/models
curl --fail --max-time 600 http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"Qwen/Qwen3-8B","messages":[{"role":"user","content":"Reply with a short greeting."}],"max_tokens":64,"temperature":0.7,"chat_template_kwargs":{"enable_thinking":false}}'
```

Confirm a nonempty assistant response. CPU latency can be substantial. The
API is unauthenticated and published only on host loopback; local host users
can call it. Do not publish it externally. Use the Praxis route below for harness
configuration; sandbox bypass denial remains a required qualification test.

```console
sudo sss-vllm select disabled
```

Disabling stops the service and removes its generated Quadlet while retaining
images and model caches. It does not delete downloaded data. Mode selection
persists in `/etc/secure-single-server/vllm-mode`; caches live under
`/var/lib/vllm-svc/cache`. A separate boot service ensures a failed vLLM pull
or preflight does not block Praxis/OpenShell startup. Failed reconciliation
retries every 30 seconds. Inspect failures with the journal commands above.

## Reproducibility and validation

[Image and model pins](../configs/vllm/images.env) belong to the OS deployment.
The CPU image is vLLM `v0.19.0-x86_64`; the GPU image is `v0.19.0`.
Both use the same immutable Hugging Face model revision. Changes require an
OS rebuild. OS rollback restores shipped pins but does not undo the selected
mode or cached data. Cached images avoid registry pulls; offline model loading
is not yet qualified because Hugging Face may still check metadata.

GPU mode disables SELinux container labeling for this container to allow CDI
access, following the reference lab. SELinux remains enforcing on the host.
The service is rootless, runs as container UID 1001, drops capabilities, and
uses private shared memory. The L4 runtime check exercises driver/CDI access with these restrictions. CPU mode keeps normal container labeling.

Local checks (the inference configuration test requires PyYAML):

```console
python3 bootc/tests/vllm.py
python3 bootc/tests/inference.py
python3 bootc/tests/build.py
shellcheck -x bootc/scripts/*
```

See [CI coverage](CI.md) for automated checks.
See the runtime report for boot, inference, sandbox and lifecycle results.
Registry-failure recovery, offline operation, OS rollback, sustained load and
additional hardware remain separate qualification work. Static rendering
tests alone do not establish model readiness or policy enforcement.

References: [vLLM CPU installation](https://docs.vllm.ai/en/v0.19.0/getting_started/installation/cpu/),
[Qwen3-8B model card](https://huggingface.co/Qwen/Qwen3-8B),
and [reference GPU launcher](https://github.com/cooktheryan/openshell-lab/blob/9b35d982bc8fea3f36a4069b1eaa0098fb9fbabd/labs/lab5/configure-vllm.sh).

## Route Praxis to the deprecated local backend

After local vLLM answers the direct health/model/chat requests, select the local
backend on the booted host:

```console
sudo sss-bootc inference vllm
sudo sss-bootc inference status
sudo sss-bootc inference check
```

`check` generates a short completion through vLLM and then through Praxis;
HTTP errors, missing models, and empty completions fail the check. It does not
qualify streaming, tool calling, the harness, or policy enforcement. Praxis
continues applying its request rate and shared in-memory token limits. A slow
CPU request can still hit runtime timeouts; this path needs load testing.

The local Praxis container uses host networking to reach vLLM's loopback port
across their separate rootless accounts. Its listeners bind only to
`127.0.0.1:8080` and admin `127.0.0.1:9901`. Port 8081 is not used. The local
configuration neither reads cloud-provider secrets nor routes to a cloud API.
An unavailable vLLM produces an upstream failure instead of a cloud fallback.
Disabling vLLM leaves the Praxis backend selection unchanged.

Selection persists in `/etc/secure-single-server/inference-backend`. To return
to the existing cloud profile, provision the usual OpenAI/Anthropic secrets and
run `sudo sss-bootc inference cloud`. Selecting cloud without secrets stops
Praxis until they are provisioned. Existing sandboxes are not reconfigured by
backend changes; avoid changing it while a sandbox is in use.

## OpenCode configuration

Use the **OpenCode** bootc variant. Once either vLLM backend is selected, this
command automatically selects the Qwen3-8B Praxis provider and dedicated dev
policy, rejecting a direct `--provider` or custom `--config` override:

```console
sudo sss-bootc harness create --profile dev --name qwen-dev
sudo sss-bootc harness connect --name qwen-dev
# From the host, run the repository smoke test against that sandbox:
sudo bootc/test-inference qwen-dev
```

Only the writable dev profile is provided for this path. Its network policy
allows the Praxis endpoint at `host.openshell.internal:8080`, with no direct
vLLM or cloud-provider endpoint. It intentionally omits package and GitHub
network access. The pinned image must supply its OpenCode provider adapter;
a missing dependency must be packaged into the image before qualification.
Both vLLM profiles enable Hermes tool-call parsing and Qwen3 reasoning parsing.
The configured context and output limits are carried through provider rendering.
Existing sandboxes retain their installed configuration and policy; recreate them
after changing these defaults.

Upstream OpenShell removed workspace-global managed inference routes and the
`openshell inference` commands in the 0.1 series; this is not an ODH-only omission.
The supported replacement is [provider profiles and per-sandbox attachments](https://github.com/NVIDIA/OpenShell/blob/v0.1.2/docs/how-it-works/inference.mdx#migrate-from-managed-inference-routes).
This example uses an explicit **OpenCode** Praxis provider configuration plus a
sandbox policy permitting only the Praxis endpoint. It does not yet import an
OpenShell provider profile or attach a provider; that integration is tracked in
[the roadmap](../docs/roadmap.md#upstream-01x-capabilities-we-do-not-use-yet).
OpenCode's canonical binary path is `/usr/local/bin/opencode`; its
`/usr/local/sbin` launcher is a symlink.

See [runtime validation](VLLM-VALIDATION.md) for the tested hardware, image revisions,
actual inference results, and remaining limits. Use the dedicated local policy;
the general development profiles intentionally permit additional network access.

CPU/GPU selection queues preparation asynchronously so a later disable command
can cancel a slow image pull. Check status and `/health` for readiness. Status
does not wait for the reconciliation lock; disabling waits for the service to stop.
