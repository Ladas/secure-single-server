# Use the remote gateway

Run the harness on your own machine, as an ordinary user. Its files and tools
run there; SSH to the gateway is unnecessary. Obtain the HTTPS URL, your caller
JWT and accepted model IDs from the administrator. Never use a provider key.

Run from a reviewed checkout on your client machine with Bash, Python 3, Git,
Node.js 22+ and npm. Use a user configuration without saved provider logins
or conflicting managed settings. Keep the
harness's normal tool approval and sandbox controls enabled.

## 1. Set the connection

Start Bash, then enter the URL and caller token. The token prompt is hidden.
Use an origin such as `https://gateway.example.com:8443`, without `/v1`.

```console
bash
```

```console
set +x
set +a
unset PRAXIS_CALLER_JWT
{
  read -r -p 'Praxis HTTPS origin: ' PRAXIS_URL
  read -r -s -p 'Caller JWT: ' PRAXIS_CALLER_JWT; printf '\n'
  read -r -p 'Private CA PEM absolute path (Enter for system trust): ' PRAXIS_CA
}
```

Copy unchanged in the same shell:

```console
PRAXIS_URL="${PRAXIS_URL%/}"
if [[ "$PRAXIS_URL" =~ ^https://[A-Za-z0-9][A-Za-z0-9.-]*(:[0-9]+)?$ && -n "$PRAXIS_CALLER_JWT" ]]; then
  export PRAXIS_URL PRAXIS_CALLER_JWT
  if [[ -n "$PRAXIS_CA" ]]; then
    export NODE_EXTRA_CA_CERTS="$PRAXIS_CA"
    export CODEX_CA_CERTIFICATE="$PRAXIS_CA"
  fi
  printf 'Connection settings loaded.\n'
else
  unset PRAXIS_URL PRAXIS_CALLER_JWT
  printf 'Invalid connection settings. Repeat the prompts before continuing.\n'
  printf 'Use an HTTPS DNS/IPv4 origin without a path, and a nonempty caller JWT.\n'
fi
```

For private-CA deployments, these are the documented trust settings for
[Claude Code](https://code.claude.com/docs/en/network-config),
[OpenCode](https://opencode.ai/docs/network/) and
[Codex](https://learn.chatgpt.com/docs/auth). Never set an insecure-TLS flag.
The JWT is a secret usable by its bearer until expiry/key rotation. The
harness process and its tools can read it; keep it out of projects and logs.

## 2. Prepare the client

After successful validation, create a private temporary JWT file and select
the shared launcher. The file contains only your caller token, never a provider key:

```console
unset HARNESS GATEWAY
if [[ -n "${PRAXIS_URL:-}" && -n "${PRAXIS_CALLER_JWT:-}" ]]; then
  CALLER_JWT="$(mktemp "${TMPDIR:-/tmp}/praxis-caller.XXXXXX")" &&
  printf '%s' "$PRAXIS_CALLER_JWT" > "$CALLER_JWT" && {
    HARNESS=(python3 "$PWD/scripts/common/harness.py")
    GATEWAY=(--url "$PRAXIS_URL" --token-file "$CALLER_JWT")
    if [[ -n "$PRAXIS_CA" ]]; then GATEWAY+=(--ca-file "$PRAXIS_CA"); fi
  }
  unset PRAXIS_CALLER_JWT
else
  unset HARNESS GATEWAY
  printf 'Repeat connection setup before continuing.\n'
fi
```

Install the pinned CLIs under your own account, without sudo:

```console
python3 - <<'PYCLIENT'
import json, pathlib, subprocess
versions = json.loads(pathlib.Path("configs/common/harness-versions.json").read_text())
subprocess.run(["npm", "install", "--global", "--prefix", str(pathlib.Path.home() / ".local"),
                *[f"{name}@{version}" for name, version in versions.items()]], check=True)
PYCLIENT
export PATH="$HOME/.local/bin:$PATH"
codex --version
claude --version
opencode --version
mkdir -p ~/projects/praxis-example
cd ~/projects/praxis-example
git init -q
```

## 3. Choose an enabled provider

### Qwen through vLLM

Choose one client. The launcher adds `/vllm` and the model's 16k context settings.
CPU inference can take several minutes. OpenCode and Claude reserve up to
4096 output tokens including thinking.

```console
"${HARNESS[@]}" opencode --provider vllm "${GATEWAY[@]}"
```

```console
"${HARNESS[@]}" claude --provider vllm "${GATEWAY[@]}"
```

```console
"${HARNESS[@]}" codex --provider vllm "${GATEWAY[@]}"
```

### OpenAI

The administrator [enables OpenAI](../common/providers.md#add-openai) and gives
you an approved model ID. Read it, then choose either client:

```console
printf 'Approved OpenAI model ID: '
IFS= read -r OPENAI_MODEL
```

```console
"${HARNESS[@]}" codex --provider openai --model "$OPENAI_MODEL" "${GATEWAY[@]}"
```

```console
"${HARNESS[@]}" opencode --provider openai --model "$OPENAI_MODEL" "${GATEWAY[@]}"
```

### Anthropic

The administrator [enables Anthropic](../common/providers.md#add-anthropic)
independently of OpenAI. Read the approved model ID, then choose either client:

```console
printf 'Approved Anthropic model ID: '
IFS= read -r ANTHROPIC_MODEL
```

```console
"${HARNESS[@]}" claude --provider anthropic --model "$ANTHROPIC_MODEL" "${GATEWAY[@]}"
```

```console
"${HARNESS[@]}" opencode --provider anthropic --model "$ANTHROPIC_MODEL" "${GATEWAY[@]}"
```

These commands retain normal tool approvals and use native APIs. They do not
enable translation between provider APIs. Cloud calls use the administrator's
provider account and billing.

## Disconnect, renew and stop

The gateway survives your logout. The harness follows your client machine's
normal lifecycle: resume a saved session using its own resume command, or
use `tmux` on a remote client host if the process must survive SSH disconnects.

On `401`, obtain a replacement JWT and repeat connection setup. On `429`, the
shared quota or request-rate protection may be exhausted. When finished,
close the harness and remove only the temporary caller file created above:

```console
rm -- "$CALLER_JWT"
unset CALLER_JWT PRAXIS_CALLER_JWT GATEWAY
```

## Model menus

The launcher selects one approved provider/model per session. OpenCode uses
`/models`; Claude and Codex use `/model`. These menus do not constitute an
automatically aggregated Praxis catalog. Keep the explicit model selection
unless the administrator has qualified another entry for this gateway.
