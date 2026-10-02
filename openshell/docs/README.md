# Harness sandboxing with OpenShell

OpenShell adds a policy-controlled execution environment around a harness and
its tools. Profiles describe filesystem, network, runtime, and service-account
boundaries, while bootc packages a reviewed host deployment.

If you are new to the architecture, start with the
[why-this-exists walkthrough](../../docs/quickstarts/architecture-walkthrough/README.md).

This repository consumes pinned OpenShell control-plane and preinstalled harness
images. The current deployment target is a dedicated, trusted single-operator
RHEL 9 x86_64 host with rootless Podman. Bootc builds one OS image per harness.

- [OpenCode and OpenClaw single-server manual and bootc guide](../../docs/quickstarts/openshell-single-server/README.md)
- [Codex experimental recipe](quickstarts/codex.md)
- [Praxis integration and status](../../docs/quickstarts/openshell-praxis/README.md)
- [Bootable host deployment](../../bootc/README.md)
- [Threat model](threat-model.md)
- [Policy test contract](policy-walkthrough.md)
- [AWS validation](../../bootc/VALIDATION.md)

The gateway controls its owner's Podman service and requires authenticated
local management with TLS/mTLS. This is not shared-host multi-tenant
authorization. Provider credentials use explicit bindings or optional Praxis;
SSH helpers do not forward them.

For CI, native runtime checks and architecture coverage, see the
[testing guide](../../docs/testing/README.md#openshell-and-bootc).
