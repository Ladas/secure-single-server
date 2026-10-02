# OpenCode harness

OpenCode provides the coding-agent experience: prompts, model choice, streaming,
and tool calls. This directory packages its lifecycle scripts and OpenShell
profiles; the architecture does not replace OpenCode with a custom agent.

The validated local path is **OpenCode → Praxis → vLLM**. OpenCode receives only
the Praxis endpoint and a placeholder API key, while the sandbox policy permits
only that endpoint. The model can still invoke tools, but those tools do not
receive direct vLLM or cloud-provider access.

Start with the [architecture value walkthrough](../../docs/quickstarts/architecture-walkthrough/README.md),
then use the [OpenCode recipe](../../docs/quickstarts/opencode.md) for setup,
commands and current limitations. Shared policy semantics and trust boundaries
are documented in the [OpenShell guide](../../docs/README.md).
For a direct manual or bootc deployment path, use the
[OpenShell single-server guide](../../../docs/quickstarts/openshell-single-server/README.md).

The preinstalled harness image is digest-pinned in `openshell/configs/images.env`.
