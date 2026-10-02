# OpenClaw harness

OpenClaw provides the coding-agent experience. This directory packages its
lifecycle scripts and OpenShell profiles so the harness does not need a broad
host login to be useful.

OpenClaw is available as a sandboxed harness recipe, but it is **not** part of
the validated local Qwen3-8B path: its current Praxis configuration is
unsupported. Use the [architecture value walkthrough](../../docs/quickstarts/architecture-walkthrough/README.md)
for the supported OpenCode path, and the [OpenClaw recipe](../../docs/quickstarts/openclaw.md)
for its standalone setup and limitations.
For a direct manual or bootc deployment path, use the
[OpenShell single-server guide](../../../docs/quickstarts/openshell-single-server/README.md).

Shared policy semantics and trust boundaries are documented in the
[OpenShell guide](../../docs/README.md). The preinstalled harness image is
digest-pinned in `openshell/configs/images.env`.
