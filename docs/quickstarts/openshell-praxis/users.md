# OpenShell user setup and usage

For mutable RHEL all-in-one, follow [manual OpenShell testing](../../testing/openshell-manual.md).
The administrator installs the addon and public recipes. You use your ordinary
SSH account to register the local gateway and run harnesses without sudo.

Start with OpenCode and Qwen through Praxis. The guide also includes an OpenAI
experiment. Codex/OpenClaw Praxis adapters and a Claude image/recipe are still
missing. The [compatibility matrix](../../testing/compatibility.md#all-in-one)
separates direct, OpenShell, CPU/GPU and mock/real results.

The management API currently trusts local users; registration does not create
a private per-user control plane. Keep management ports on loopback. See the
[deployment boundary](../../../openshell/docs/threat-model.md).

For bootc installations, use the [bootc workflow](../../../bootc/README.md)
and its [recorded validation](../../../bootc/VLLM-VALIDATION.md). Bootc results
do not qualify the mutable RHEL sandbox workflow.
