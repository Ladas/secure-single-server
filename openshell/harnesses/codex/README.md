# Codex harness

Codex provides the coding-agent experience. This directory packages its
lifecycle scripts and OpenShell profiles so an administrator can choose which
filesystem and network access the harness receives.

Codex is available as a sandboxed harness recipe, but it is **not** part of the
validated local Qwen3-8B path: its current Praxis configuration is unsupported.
Use the [architecture value walkthrough](../../docs/quickstarts/architecture-walkthrough/README.md)
for the supported OpenCode path, and the [Codex recipe](../../docs/quickstarts/codex.md)
for its standalone setup and limitations.

Shared policy semantics and trust boundaries are documented in the
[OpenShell guide](../../docs/README.md). The preinstalled harness image is
digest-pinned in `openshell/configs/images.env`.
