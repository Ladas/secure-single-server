# OpenClaw harness

OpenClaw provides the coding-agent experience. This directory packages its
lifecycle scripts, pinned image reference, and OpenShell profiles so the
harness does not need a broad host login to be useful.

Deploy and test OpenClaw from the
[OpenShell single-server guide](../../../docs/quickstarts/openshell-single-server/README.md).
Its current sandbox path opens a shell; the service command, authentication,
browser workflow, `--backend`, and Praxis integration are not qualified.

The preinstalled harness image is digest-pinned in `openshell/configs/images.env`.
