# Harness sandboxing with OpenShell

OpenShell adds a policy-controlled execution environment around a harness and its
tools. Profiles describe filesystem access and network destinations; Praxis can
add shared model access and quotas, while bootc packages the host setup.

This repository consumes pinned OpenShell control-plane and preinstalled harness
images. The current deployment target is a disposable, trusted single-operator
RHEL 9 x86_64 host with rootless Podman. Bootc builds one OS image per harness.

- [Codex recipe](quickstarts/codex.md)
- [OpenCode recipe](quickstarts/opencode.md)
- [OpenClaw recipe](quickstarts/openclaw.md)
- [Praxis integration and status](../../docs/quickstarts/openshell-praxis/README.md)
- [Bootable host deployment](../../bootc/README.md)
- [Threat model](threat-model.md)
- [Policy test contract](policy-walkthrough.md)
- [AWS validation](../../bootc/VALIDATION.md)

The gateway controls its owner's Podman service and permits unauthenticated local
operators. This is not shared-host multi-tenant authorization. Provider credentials
use explicit bindings or Praxis; SSH helpers do not forward them.

For CI, native runtime checks and architecture coverage, see the
[testing guide](../../docs/testing/README.md#openshell-and-bootc).
