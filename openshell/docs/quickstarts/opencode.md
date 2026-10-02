# OpenCode sandbox recipe (experimental)

Follow the [shared setup](common.md), selecting `harness=opencode` and the dev
profile. The default sandbox name is `opencode-dev`; `connect.sh` launches OpenCode.
The review profile currently fails to create the CLI data directory; use dev for
CLI experiments.
For the complete manual or bootc path, start with the
[OpenShell single-server guide](../../../docs/quickstarts/openshell-single-server/README.md).

OpenCode has an experimental [Praxis configuration path](../../../docs/quickstarts/openshell-praxis/users.md).
This does not qualify host routing, inference or tool tasks. Integrated mode rejects
`--provider`; standalone experiments require an explicit binding. See [AWS validation](../../../bootc/VALIDATION.md).
