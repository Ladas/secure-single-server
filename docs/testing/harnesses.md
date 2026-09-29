# Manual harness testing

Complete [real-provider setup](rhel-real.md), then choose a client location
and an enabled provider. For all-in-one, first complete
[personal login setup](../quickstarts/all-in-one/accounts.md), which installs the pinned CLIs under
your own home. Service installation and provider credentials belong to the
administrator; every command below runs as an ordinary user.

## 1. Choose the client

**On all-in-one**, in your `praxis-user` SSH session:

```console
export PATH="$HOME/.local/bin:$PATH"
HARNESS=(praxis-harness)
GATEWAY=()
```

**On the workstation, connecting to remote-gateway**, from the deployment checkout:

```console
CLIENT_STATE="$PWD/.state/rhel-${REMOTE_GATEWAY_HOST/@/-}"
CALLER_JWT="$CLIENT_STATE/manual-$(date -u +%Y%m%dT%H%M%S).jwt"
scripts/remote-gateway/credentials issue --key "$CLIENT_STATE/issuer/private.pem" \
  --subject manual-user --days 1 --output "$CALLER_JWT"
HARNESS=(python3 "$PWD/scripts/common/harness.py")
GATEWAY=(--url "https://${REMOTE_GATEWAY_HOST#*@}:8443" \
  --ca-file "$CLIENT_STATE/tls-local-client/ca.pem" --token-file "$CALLER_JWT")
```

The workstation needs Python 3, Git, Node.js 22+ and npm. In a clean client
account, install the same CLI versions as the smoke suite:

```console
python3 - <<'PYCLIENT'
import json, pathlib, subprocess
versions = json.loads(pathlib.Path("tests/rhel/harness-versions.json").read_text())
subprocess.run(["npm", "install", "--global", "--prefix", str(pathlib.Path.home() / ".local"),
                *[f"{name}@{version}" for name, version in versions.items()]], check=True)
PYCLIENT
export PATH="$HOME/.local/bin:$PATH"
```

Keep the JWT signing key private;
other clients receive only their caller JWT and CA certificate. Use a clean
client account without saved personal provider credentials.

## 2. Create a test project

Run on the client machine, before starting a harness:

```console
TEST_PROJECT="$(mktemp -d "$HOME/praxis-acceptance.XXXXXX")"
cd "$TEST_PROJECT"
git init -q
```

## 3. Choose a provider and harness

### Qwen

No cloud key is needed. The launcher selects `qwen3-8b` through `/vllm/v1`.
Start with OpenCode:

```console
"${HARNESS[@]}" opencode --provider vllm "${GATEWAY[@]}"
```

Codex and Claude commands are available for compatibility testing; the pinned
vLLM version has the [limitations below](#backend-compatibility):

```console
"${HARNESS[@]}" codex --provider vllm "${GATEWAY[@]}"
```

```console
"${HARNESS[@]}" claude --provider vllm "${GATEWAY[@]}"
```

### OpenAI

First [enable OpenAI on the server](rhel-real.md#3-add-openai-to-existing-praxis).
Choose a model available to your account:

```console
printf 'OpenAI model ID: '
IFS= read -r OPENAI_MODEL
```

```console
"${HARNESS[@]}" codex --provider openai --model "$OPENAI_MODEL" "${GATEWAY[@]}"
```

```console
"${HARNESS[@]}" opencode --provider openai --model "$OPENAI_MODEL" "${GATEWAY[@]}"
```

### Anthropic

First [enable Anthropic on the server](rhel-real.md#4-add-anthropic-independently).
Choose a model available to your account:

```console
printf 'Anthropic model ID: '
IFS= read -r ANTHROPIC_MODEL
```

```console
"${HARNESS[@]}" claude --provider anthropic --model "$ANTHROPIC_MODEL" "${GATEWAY[@]}"
```

```console
"${HARNESS[@]}" opencode --provider anthropic --model "$ANTHROPIC_MODEL" "${GATEWAY[@]}"
```

The interactive launcher retains each CLI's normal tool permissions. Cloud
calls use the server's real credentials and may incur provider charges.

## 4. Exercise tools and check the result

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

## Backend compatibility

See the [compatibility and test matrix](compatibility.md) for exact versions,
mock versus real results, remaining failures and fix locations.

OpenCode/Qwen passed the explicit tool smoke task on CPU and GPU. Codex/Qwen
and Claude/Qwen fail with the pinned backend on CPU/GPU; direct bypass
reproduced both failures on GPU. The direct CPU control remains pending.
Cloud-provider paths passed with mocks; real OpenAI/Anthropic calls still need
manual validation. These are separate acceptance results.

For longer acceptance runs, test [remote TLS/JWT](remote-gateway.md), a second
user, logout/reboot, shared quota exhaustion and Valkey persistence. Follow
[AWS cleanup](aws-operations.md#cleanup) when finished. For sandbox execution,
follow [manual OpenShell testing](openshell-manual.md); its tested and pending
combinations are separate from direct harness results.
