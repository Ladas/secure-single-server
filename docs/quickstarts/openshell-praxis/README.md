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
explains the problem, follows the recorded Qwen path, and shows which
checks actually prove the boundary.

Service health alone does not qualify that complete model path.

See the [supported matrix and qualification limits](users.md), [add-on installer](install.md),
[bootc deployment](../../../bootc/README.md), and [threat model](../../../openshell/docs/threat-model.md).
Codex/OpenClaw Praxis configuration is currently unsupported. OpenCode configuration
remains experimental; qualification depends on the host, provider and tool task.

Development profiles also permit selected GitHub/package/documentation traffic;
they are not restricted to Praxis for all egress. Loopback management requires
TLS/mTLS for the service operator; individual user/workspace authorization is
not implemented.

For Qwen3-8B on a separate server, see the [vLLM/Praxis workflow](../../../bootc/VLLM.md).
It includes private AWS endpoint discovery, a loopback Praxis upstream, and an
OpenCode dev configuration with a dedicated Praxis-only policy. Its updated
OpenShell pins provide host-alias routing; see the linked guide for runtime evidence.
