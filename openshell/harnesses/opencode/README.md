# OpenCode harness

OpenCode provides the coding-agent experience: prompts, model interactions,
and tool calls. This directory packages its lifecycle scripts, pinned image
reference, and OpenShell profiles; it does not replace OpenCode with a custom
agent.

Deploy and test OpenCode from the
[OpenShell single-server guide](../../../docs/quickstarts/openshell-single-server/README.md).
The optional Praxis route is documented separately for administrators who
select it. In that route, tools do not receive direct vLLM or cloud-provider
access. In standalone OpenShell mode, selected model endpoints remain governed
by the harness policy.

The preinstalled harness image is digest-pinned in `openshell/configs/images.env`.
