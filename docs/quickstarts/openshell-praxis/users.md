# Experimental Praxis integration

The shared bootc base starts Praxis and OpenShell. This does not establish that
every harness can complete a task through Praxis.

Management requires the service operator's TLS client identity. Ordinary SSH
accounts are not enrolled; [#12](https://github.com/redhat-et/secure-single-server/issues/12)
tracks individual access and workspace authorization. Use
[direct harnesses](../all-in-one/users.md) until that is available; do not
copy the operator's keys to user accounts.

| Combination | Status |
| --- | --- |
| Codex + Praxis | Unsupported; `--config` fails before creating anything |
| OpenClaw + Praxis | Unsupported; `--config` fails before creating anything |
| Claude Code + Praxis | Sandbox image and recipe are missing |
| OpenCode + Praxis dev | Experimental; qualify each host, provider and tool task |
| OpenCode review | CLI data-directory permission limitation; outside supported recipes |

For OpenCode experiments, run as the OpenShell service account with the explicit
HOME/user-bus environment from the
[OpenShell single-server guide](../openshell-single-server/README.md#manual-rhel-deployment):

```bash
export OPENSHELL_MODEL_ID=administrator-approved-model
openshell/harnesses/opencode/create.sh --profile dev --config configs/openshell-praxis
```

For mutable RHEL Qwen, export `OPENSHELL_MODEL_ID=qwen3-8b` and
`PRAXIS_API_PREFIX=/vllm` in that service-account environment before creation.
Leave the prefix empty for the OpenAI cloud route or bootc local inference.

`PRAXIS_PORT` defaults to 8080 and must be an integer from 1 through 65535.
The script renders the numeric policy port and JSON model safely, selects the
Praxis model, and uploads config to `~/.config/opencode/opencode.json`. The actual
binary paths, alias route, tools and streaming must pass native qualification
before use with real credentials. A successful config upload is not inference.
Integrated mode rejects `--provider` and SSH helpers never forward provider keys.

The policies intend to limit model traffic to `host.openshell.internal`; dev,
automation and interactive also permit development endpoints. GitHub API access
is read-only, but Git-over-HTTPS is not. Filesystem permissions do not establish
workspace mounts, retention after deletion, or disconnected task persistence.

A timeout, SSH failure, or HTTP 401 does not prove a policy denial.
Delete test sandboxes with `openshell sandbox delete NAME`; do not source libraries
into your terminal. See [threat model](../../../openshell/docs/threat-model.md).
