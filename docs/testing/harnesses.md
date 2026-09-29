# Manual harness acceptance

Complete [real-provider setup](rhel-real.md). For **all-in-one**, use the
[ordinary-user guide](../quickstarts/all-in-one/users.md) to install/start a
harness, then run the [acceptance task](#acceptance-task) below.

For **remote-gateway**, prepare the workstation client below. Provider keys
remain on the server. The [compatibility matrix](compatibility.md) records
which combinations passed and which still need fixes or live tests.

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
HARNESS=(python3 "$PWD/scripts/common/harness.py")
GATEWAY=(--url "https://${RHEL_HOST#*@}:8443" \
  --ca-file "$CLIENT_STATE/tls-local-client/ca.pem" --token-file "$CALLER_JWT")
```

Install the pinned CLIs in an ordinary workstation account without saved
personal provider credentials. Do not use sudo:

```console
python3 - <<'PYCLIENT'
import json, pathlib, subprocess
versions = json.loads(pathlib.Path("tests/rhel/harness-versions.json").read_text())
subprocess.run(["npm", "install", "--global", "--prefix", str(pathlib.Path.home() / ".local"),
                *[f"{name}@{version}" for name, version in versions.items()]], check=True)
PYCLIENT
export PATH="$HOME/.local/bin:$PATH"
TEST_PROJECT="$(mktemp -d "$HOME/praxis-acceptance.XXXXXX")"
cd "$TEST_PROJECT"
git init -q
```

## Choose a remote provider and harness

### Qwen

Start with OpenCode:

```console
"${HARNESS[@]}" opencode --provider vllm "${GATEWAY[@]}"
```

For Codex/Claude testing, check the remote-gateway matrix first; the current
all-in-one results do not qualify remote clients:

```console
"${HARNESS[@]}" codex --provider vllm "${GATEWAY[@]}"
```

```console
"${HARNESS[@]}" claude --provider vllm "${GATEWAY[@]}"
```

### OpenAI

First [enable OpenAI on the server](rhel-real.md#3-add-openai-to-existing-praxis).
Enter an approved model ID, then choose one client:

```console
printf 'OpenAI model ID: '
IFS= read -r OPENAI_MODEL
"${HARNESS[@]}" codex --provider openai --model "$OPENAI_MODEL" "${GATEWAY[@]}"
```

```console
"${HARNESS[@]}" opencode --provider openai --model "$OPENAI_MODEL" "${GATEWAY[@]}"
```

### Anthropic

First [enable Anthropic](rhel-real.md#4-add-anthropic-independently).
Enter an approved model ID, then choose one client:

```console
printf 'Anthropic model ID: '
IFS= read -r ANTHROPIC_MODEL
"${HARNESS[@]}" claude --provider anthropic --model "$ANTHROPIC_MODEL" "${GATEWAY[@]}"
```

```console
"${HARNESS[@]}" opencode --provider anthropic --model "$ANTHROPIC_MODEL" "${GATEWAY[@]}"
```

Interactive clients retain their normal tool approvals. Real cloud calls use
the administrator's provider account.

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
