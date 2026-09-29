# Current vLLM issues

This page tracks bugs with **vLLM 0.30.0**, Qwen3-8B thinking enabled and the
published **Praxis PR #40 image**. It does not qualify API translation.
Results, exact pins and performance belong in the
[compatibility matrix](compatibility.md).

[vLLM 0.30.0](https://github.com/vllm-project/vllm/releases/tag/v0.30.0) is an
official release with separate CPU/GPU images. Praxis uses
`quay.io/opendatahub/praxis-experimental@sha256:227d421e963c477038a884dc51ec880c5d0afa30098ae31028ecf85e963e40d5`,
whose source label matches [PR #40](https://github.com/praxis-proxy/experimental/pull/40),
revision `019aa849a219e5c881d69e4a40a1fc190bd6c404`.

All three direct harness tasks pass through Praxis on both all-in-one CPU and
GPU. These smoke results do not establish general coding reliability.

## Responses tool IDs change between stream and final response

The same captured request reproduces this on GPU through the new Praxis image
and directly against vLLM 0.30: all three tool calls change `id`/`call_id` between
`response.output_item.done` and `response.completed`. Arguments match, and the
Codex task passes, but clients that correlate by ID may fail.

[vLLM #44676](https://github.com/vllm-project/vllm/issues/44676) reports this ID
drift as a secondary finding; its main thinking-budget bug uses another model.
The [0.30 response builder](https://github.com/vllm-project/vllm/blob/v0.30.0/vllm/entrypoints/openai/responses/serving.py)
has a **source-code TODO** to reuse accumulated stream items rather than reparse
complete output. That comment contains no issue reference. No separate issue or
patch has been submitted for our reproduction.

Fix candidate: add a regression requiring stable IDs and reuse the accumulated
stream objects in vLLM. Recheck individual tool arguments, IDs, continuation and
terminal usage. Praxis translation is a separate, untested workaround and may
need AI changes for streaming reasoning; an image update alone does not enable it.

## Private vLLM requests returned 502 after the Praxis upgrade

**Fixed in this branch.** The new Praxis image enforces a runtime private-IP
check. Our generated local-provider configuration allowed private endpoints at
startup but omitted `insecure_options.allow_private_upstreams`. Direct access
from the Praxis container succeeded while forwarded requests failed on CPU/GPU.

The renderer now enables both settings when local vLLM is selected; cloud-only
production configurations keep the runtime check. Mock fixtures explicitly
allow their private endpoints. This is a deployment configuration fix, not a
vLLM defect. Use the managed installer to apply it; do not edit installed files
outside the manifest.
