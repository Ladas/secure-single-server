# Inference CI

Every PR runs the existing build/profile tests plus a Linux lock-contention
regression and the pinned Praxis image against a synthetic OpenAI server on
both amd64 and arm64. The image test uses the shipped local profile unchanged:
model listing, chat, SSE tool-call payloads, request-header stripping and HTTP
502 when the only upstream disappears. It downloads no model weights and uses
no provider credentials. This tests protocol forwarding, not model quality or
GPU execution. The OpenShell static and native schema checks include the local
vLLM harness policy, and local config changes trigger the OpenShell workflow.

Run the new tests on a Linux host with Python 3, Bash, util-linux and Docker
(or Podman). The container engine must run on that same host; a remote Docker
or Podman VM cannot reach the Python mock server's host loopback. Ports 8000,
8080 and 9901 must be free.

```console
python3 bootc/tests/vllm-lock.py
python3 bootc/tests/select-images.py
python3 bootc/tests/praxis.py
python3 bootc/tests/inference.py
python3 tests/aws/plan.py
python3 tests/aws/session.py
python3 tests/rhel/providers.py
python3 tests/rhel/vllm.py
CONTAINER_ENGINE=docker python3 bootc/tests/inference-image.py
```

## Bootc image CI

`.github/workflows/bootc-images.yml` builds only the image groups whose inputs
changed. Pull requests build and test locally but do not publish. Pushes to
`main` publish the selected images to `quay.io/redhat-et` with the release-facing
`v0.1` tag and immutable `sha-<commit>` audit tags.

The workflow authenticates to `registry.redhat.io` with a Red Hat registry
service account and uses `RHSM_ORG_ID` plus `RHSM_ACTIVATION_KEY` as ephemeral
Podman build secrets for package installation. It never copies registry
credentials, activation keys, entitlement certificates, or subscription state
into an image layer.

Published repositories:

- The `base` image is built and tested as the internal harness parent but is
  not published.
- `quay.io/redhat-et/secure-single-server-praxis:v0.1`
- `quay.io/redhat-et/secure-single-server-vllm-cpu:v0.1`
- `quay.io/redhat-et/secure-single-server-vllm-gpu:v0.1`
- `quay.io/redhat-et/secure-single-server-codex:v0.1`
- `quay.io/redhat-et/secure-single-server-opencode:v0.1`
- `quay.io/redhat-et/secure-single-server-openclaw:v0.1`

Required GitHub configuration:

- Repository variable: `RHEL_BOOTC_IMAGE`
- Protected environment `bootc-image-pr` with required reviewers for
  same-repository pull-request builds
- Environment `bootc-image-main` for trusted `main` and manual builds
- Repository secrets: `REDHAT_REGISTRY_USERNAME`,
  `REDHAT_REGISTRY_PASSWORD`, `RHSM_ORG_ID`, `RHSM_ACTIVATION_KEY`,
  `QUAY_USERNAME`, and `QUAY_TOKEN`

## Scope

All new jobs run on the existing standard GitHub-hosted Ubuntu amd64 and arm64
runners. No self-hosted runners, AWS resources, GPU, model downloads or cloud
credentials are required. The existing optional OpenShell runtime fixture is
unchanged and is not part of these hosted checks.

These tests do not qualify real Qwen inference, GPU driver/CDI behavior, bootc
boot/reboot, sandbox enforcement, or OS rollback. See the separate hardware
results in [VLLM-VALIDATION.md](VLLM-VALIDATION.md). Green PR checks should not be
interpreted as fresh hardware validation.

## Shared test foundation

The inference checks extend the shared test foundation merged in
[PR #5](https://github.com/redhat-et/secure-single-server/pull/5).

The local inference check imports `tests/common/provider.py`,
`tests/common/contracts.py` and `tests/common/evidence.py` from that foundation.
It adds only the local profile's model name, absent-authorization contract,
unchanged loopback configuration and unavailable-backend check. Cloud protocol,
JWT/TLS, quota and Valkey cases run once in the shared matrix. Both native and
container OpenShell schema runners use the same positive/negative controls,
now covering the additional local policy (17 policies total).
