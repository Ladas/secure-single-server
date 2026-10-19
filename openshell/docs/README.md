# Harness sandboxing with OpenShell

> **Where this fits:** The execution-boundary deep dive. Start with the
> architecture walkthrough if you are new to the complete system.

OpenShell adds a policy-controlled execution environment around a harness and
its tools. Profiles describe filesystem, network, runtime, and service-account
boundaries, while bootc packages a reviewed host deployment.

If you are new to the architecture, start with the
[why-this-exists walkthrough](../../docs/quickstarts/architecture-walkthrough/README.md).

This repository consumes pinned OpenShell control-plane and preinstalled harness
images. The current deployment target is a dedicated, trusted single-operator
RHEL 9 x86_64 host with rootless Podman. Bootc builds one OS image per harness.
The host and bootc OS remain RHEL 9; the upstream OpenShell 0.1.4 and OpenClaw
2026.9.9 workload containers use Debian-based runtimes. See the
[0.1.4 pin review](../../docs/testing/upgrade-0.1.4.md) and the historical
[0.1.3 upgrade qualification](../../docs/testing/upgrade-0.1.3.md).

- [Manual OpenShell and harness deployment](../../docs/quickstarts/openshell-single-server/manual.md)
- [Bootc OpenShell and harness deployment](../../docs/quickstarts/openshell-single-server/bootc.md)
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

## Next step

Read the [policy qualification contract](policy-walkthrough.md), then deploy a
harness with the [single-server guide](../../docs/quickstarts/openshell-single-server/README.md).
