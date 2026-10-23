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
| OpenClaw + Praxis | Experimental dev profile; [bounded read/write workflow](openclaw.md); [historical 0.1.3 fixture qualification](../../testing/upgrade-0.1.3.md) |
| Claude Code + Praxis | Sandbox image and recipe are missing |
| OpenCode + Praxis dev | Experimental; [historical 0.1.3 model, write and bash fixture qualification](../../testing/upgrade-0.1.3.md); qualify each real host/provider/model task on the current pins |
| OpenCode + Praxis pr-queue | Experimental [PR-candidate example](../../examples/opencode-pr-queue/README.md); static, schema, and policy-boundary contracts only |
| OpenCode review | CLI data-directory permission limitation; outside supported recipes |

For OpenClaw, use the [dedicated model and tool walkthrough](openclaw.md).

For OpenCode experiments, run as the OpenShell service account using the `os_run` helper from the
[OpenShell single-server guide](../openshell-single-server/manual.md):

```bash
os_run env OPENSHELL_MODEL_ID=administrator-approved-model \
  "$repo/openshell/harnesses/opencode/create.sh" \
  --profile dev --config "$repo/configs/openshell-praxis"
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

The policies limit Praxis traffic to `GET /v1/models`,
`POST /v1/chat/completions`, and `POST /v1/responses` on
`host.openshell.internal`, with the configured route prefix such as `/vllm`
prepended to all three paths. With `/vllm`, for example, the effective paths
are `/vllm/v1/models`, `/vllm/v1/chat/completions`, and
`/vllm/v1/responses`. The OpenCode `pr-queue` profile permits the third path
so it can use OpenCode's built-in provider without npm access. Dev, automation,
and interactive also permit development endpoints. GitHub API access is read-only,
and Git Smart HTTP permits clone/fetch but not push. Filesystem permissions do
not establish workspace mounts, retention after deletion, or disconnected task
persistence.

The `pr-queue` profile is intentionally narrower: it permits only Praxis,
read-only GitHub API, and Git clone/fetch traffic. Start with the
[PR-candidate example](../../examples/opencode-pr-queue/README.md), which also
maps the profile to its runner, collector, agent instructions, and tests. That
workflow has not yet received a real-provider runtime qualification.

A timeout, SSH failure, or HTTP 401 does not prove a policy denial.
Delete test sandboxes with `openshell sandbox delete NAME`; do not source libraries
into your terminal. See the [OpenShell Overview](../../../openshell/docs/README.md).
