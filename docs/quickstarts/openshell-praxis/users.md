# Experimental Praxis integration

The shared bootc base starts Praxis and OpenShell. This does not establish that
every harness can complete a task through Praxis.

| Combination | Status |
| --- | --- |
| Codex + Praxis | Unsupported; `--config` fails before creating anything |
| OpenClaw + Praxis | Unsupported; `--config` fails before creating anything |
| OpenCode + Praxis dev | Experimental config rendering; inference/tool-task qualification required |
| OpenCode review | CLI data-directory permission limitation; outside supported recipes |

For OpenCode experiments, run as the OpenShell service account with the explicit
HOME/user-bus environment from the [OpenCode recipe](../../../openshell/docs/quickstarts/opencode.md):

```bash
export OPENSHELL_MODEL_ID=administrator-approved-model
openshell/harnesses/opencode/create.sh --profile dev --config configs/openshell-praxis
```

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

`tests/openshell-praxis/smoke.sh` requires a preconfigured Praxis/mock-provider
fixture and an approved test model. It requires successful inference and runs the
controlled policy probe. A timeout, SSH failure, or HTTP 401 does not prove denial.
This qualification suite is separate from the opt-in standalone runtime CI suite.
Delete test sandboxes with `openshell sandbox delete NAME`; do not source libraries
into your terminal. See [threat model](../../../openshell/docs/threat-model.md).
