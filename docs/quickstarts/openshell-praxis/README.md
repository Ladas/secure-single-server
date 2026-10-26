# OpenShell + Praxis (experimental)

> **Where this fits:** Step 3 of the recommended route. Add this only after the
> OpenShell deployment and its intended harness are selected.

Harnesses are good at prompts, tools, and developer workflow. They are not a
host-security boundary, a credential manager, or a shared model budget.

OpenShell controls where a harness and its tools execute. Praxis centralizes
model routing, provider credentials, and shared token limits. Together, the
intended model path is a sandboxed harness → Praxis → upstream provider. The
bootc base packages both services and the selected harness configuration into
one updatable OS deployment.

For an informational view of the components and model access paths, see the
[Architecture overview](../architecture-walkthrough/README.md). Deployment
and validation procedures are documented separately.

Service health alone does not qualify that complete model path.

See the [supported matrix and qualification limits](users.md), [add-on installer](install.md),
[bootc deployment](../../../bootc/README.md), and [OpenShell Overview](../../../openshell/docs/README.md).
[OpenClaw bounded tasks](openclaw.md) and OpenCode configuration remain
experimental; qualification depends on the host, provider and tool task.

Development profiles also permit selected GitHub/package/documentation traffic;
they are not restricted to Praxis for all egress. Loopback management requires
TLS/mTLS for the service operator; individual user/workspace authorization is
not implemented.

For Qwen3-8B on a separate server, see the [vLLM/Praxis workflow](../../../bootc/VLLM.md).
It includes private AWS endpoint discovery, a loopback Praxis upstream, and an
OpenCode dev configuration with a dedicated Praxis-only policy. Its updated
OpenShell pins provide host-alias routing; see the linked guide for runtime evidence.

## Next step

- Choose the inference path through the
  [common configuration index](../common/README.md).
- Check the [integration matrix](users.md) before claiming support for a
  harness or provider.
