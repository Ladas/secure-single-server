# OpenShell user access

The addon now requires TLS and a client certificate for its local management
API. The installer registers the dedicated `openshell-svc` operator account.
An ordinary SSH login does **not** receive that identity automatically.

Individual user enrollment and workspace authorization are not implemented;
[issue #12](https://github.com/redhat-et/secure-single-server/issues/12) tracks
that work. Keep using [direct harnesses in your own account](../all-in-one/users.md)
for Qwen, OpenAI and Anthropic. Do not copy the operator's certificate/key or
service home into user accounts, or disable management authentication.

The administrator can [install the addon](install.md). OpenCode has an
experimental Praxis sandbox recipe; Codex/OpenClaw need Praxis adapters, and
Claude needs a pinned image and recipe. Service-operator sandbox execution does
not establish personal-user access or private workspaces.

For bootc installations, use the [bootc workflow](../../../bootc/README.md).
See the [deployment boundary](../../../openshell/docs/threat-model.md) for the
remaining shared-operator limitations.
