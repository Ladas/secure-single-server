# OpenShell + Praxis (experimental)

OpenShell controls where a harness and its tools execute. Praxis centralizes
provider access and shared token limits. Together, the intended model path is
a sandboxed harness → Praxis → upstream provider.
Praxis owns provider credentials; harnesses should only use its local inference
endpoint. The bootc base packages both services and the selected harness configuration
into one updatable OS deployment. Service health alone does not qualify that
complete model path.

See the [user access and current limitations](users.md), [add-on installer](install.md),
[bootc deployment](../../../bootc/README.md), and [threat model](../../../openshell/docs/threat-model.md).
Codex/OpenClaw Praxis configuration is currently unsupported. OpenCode/Qwen has
real CPU/GPU evidence on bootc; mutable RHEL qualification is separate. For the
existing all-in-one VM, follow [administrator installation](install.md), then
[user access limitations](users.md).

Development profiles also permit selected GitHub/package/documentation traffic;
they are not restricted to Praxis for all egress. Loopback management requires
TLS/mTLS for the service operator. Separate user/workspace authorization is still missing; see [user access](users.md).

For local Qwen3-8B on bootc, see the [vLLM/Praxis workflow](../../../bootc/VLLM.md).
It includes CPU/GPU serving, a loopback Praxis upstream, and an OpenCode dev
configuration with a dedicated Praxis-only policy. Its updated OpenShell pins
provide host-alias routing; see the linked guide for runtime evidence.
