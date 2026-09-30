# Manual harness acceptance

Complete [real-provider setup](rhel-real.md). For **all-in-one**, use the
[ordinary-user guide](../quickstarts/all-in-one/users.md) to install/start a
harness, then run the [acceptance task](#acceptance-task) below.

For **remote-gateway**, prepare the workstation client below. Provider keys
remain on the server. The [compatibility matrix](compatibility.md) records
which combinations passed and which still need fixes or live tests.

<details>
<summary>What the launcher configures, and how to compare file-based alternatives</summary>

The [configuration reference](../quickstarts/common/harness-configuration.md)
shows Codex flags/TOML, OpenCode environment JSON/config files, and Claude
environment/settings files. The normal acceptance path uses `praxis-harness`
without `--prompt`, preserving interactive approvals. `--prompt` selects the
bounded automated tool task mode; record that distinction.

When testing a file-based alternative, record the config source and verify the
same endpoint, model, context/output limits, thinking and authentication before
running the task below. Record its result separately: launcher passes do not
qualify a manually maintained file. A generated configuration is not evidence
that the CLI discovered models from Praxis. Record catalog/discovery and
post-selection inference with the [feature matrix](gateway-features.md).

</details>

## Remote-gateway client

On the workstation, select the gateway with `aws_test_verify remote-gateway-cpu`
or `aws_test_verify remote-gateway-gpu`. Run from the deployment checkout.
You need Python 3, Git, Node.js 22+ and npm.

The administrator issues a short-lived caller JWT from the runner's private
state. Other users receive only their JWT and the public CA certificate:

```console
CLIENT_STATE="$PWD/.state/rhel-${RHEL_HOST/@/-}"
CALLER_JWT="$CLIENT_STATE/manual-$(date -u +%Y%m%dT%H%M%S).jwt"
scripts/remote-gateway/credentials issue --key "$CLIENT_STATE/issuer/private.pem" \
  --subject manual-user --days 1 --output "$CALLER_JWT"
```

Give the user that JWT file, the public certificate
`$CLIENT_STATE/tls-local-client/ca.pem`, the HTTPS URL and approved model IDs.
Follow [remote client setup](../quickstarts/remote-gateway/users.md) for pinned
CLI installation and Qwen/OpenAI/Anthropic commands. The user never receives
the issuer key or provider keys. Use a fresh project for each combination,
then run the task below.

## Acceptance task

Give the harness this task:

```text
Create add.py with an add(a, b) function and test_add.py using Python unittest.
Import add from add.py. Test positive numbers, negative numbers and zero.
Run python3 -m unittest -v and fix failures before finishing.
Use only the standard library and work only in this project.
```

Approve the expected project file/test operations. After leaving the harness:

```console
test -f add.py && test -f test_add.py && python3 -m unittest -v
```

Require file creation, a successful test-tool execution and continuation after
the tool result. Repeat in a fresh project for each harness/provider. A model's
claim that tests passed is insufficient.

For sandbox execution, use [OpenShell testing](openshell-manual.md).
Record direct and sandbox results separately in the [matrix](compatibility.md).

## Model-selector checks

Use the same ordinary-user launcher and provider settings as the task test.
Open the selector without submitting a prompt:

| Harness | Selector | Expected with the current Qwen setup |
| --- | --- | --- |
| Codex | `/model` | Qwen is missing; keep the explicit launcher selection |
| Claude Code | `/model` | Qwen appears through configured aliases |
| OpenCode | `/models` | Qwen appears under Praxis |

Record the visible model ID, whether it came from local configuration or a
fetched catalog, and the exact CLI version. Then select the approved entry,
submit a short prompt and confirm that Praxis received the chosen model ID.
Record listing and post-selection inference separately; an API model-list probe
or a task launched with `--model` does not prove either menu interaction.

Repeat for each enabled cloud provider and remote-client configuration. A menu
entry does not establish that the administrator's provider account can use it.
For OpenShell, run inside the sandbox and record the service-operator versus
personal-user access mode. Results are grouped by setup in the
[compatibility matrix](compatibility.md).

Provider configuration references: [Codex model catalog](https://learn.chatgpt.com/docs/config-file/config-reference),
[OpenCode custom providers](https://opencode.ai/docs/providers#custom-provider),
and [Claude model configuration](https://code.claude.com/docs/en/model-config).
These describe configuration; the matrix records the installed versions' results.
