# OpenShell + Praxis (experimental)

Harnesses are good at prompts, tools, and developer workflow. They are not a
host-security boundary, a credential manager, or a shared model budget.

OpenShell controls where a harness and its tools execute. Praxis centralizes
model routing, provider credentials, and shared token limits. Together, the
intended model path is a sandboxed harness → Praxis → upstream provider. The
bootc base packages both services and the selected harness configuration into
one updatable OS deployment.

If you are evaluating the idea, start with the
[architecture value walkthrough](../architecture-walkthrough/README.md). It
explains the problem, follows the validated local Qwen path, and shows which
checks actually prove the boundary.

Service health alone does not qualify that complete model path.

See the [supported matrix and qualification limits](users.md), [add-on installer](install.md),
[bootc deployment](../../../bootc/README.md), and [threat model](../../../openshell/docs/threat-model.md).
Codex/OpenClaw Praxis configuration is currently unsupported. OpenCode configuration
has two distinct states: the generic add-on remains experimental, while the
dedicated local vLLM path has recorded host-alias routing, real inference, tool
execution and policy-denial evidence.

Generic development profiles also permit selected GitHub/package/documentation
traffic; they are not restricted to Praxis for all egress. The dedicated local
vLLM policy intentionally omits that access. Loopback management trusts local
host users, and is not a multi-tenant authorization boundary.

For local Qwen3-8B on bootc, see the [vLLM/Praxis workflow](../../../bootc/VLLM.md).
It includes CPU/GPU serving, a loopback Praxis upstream, and an OpenCode dev
configuration with a dedicated Praxis-only policy. Its updated OpenShell pins
provide host-alias routing; see the linked guide for runtime evidence.
