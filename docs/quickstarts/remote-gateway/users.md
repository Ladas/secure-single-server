# Use the remote gateway

Run the harness on your own machine, as an ordinary user. Its files and tools
run there; SSH to the gateway is unnecessary. Obtain the HTTPS URL, your caller
JWT and accepted model IDs from the administrator. Never use a provider key.

These commands use Bash, `curl` and `jq`. Use a clean test account/configuration
without saved provider logins or conflicting managed settings. Keep the
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
harness process and its tools can read it; keep it out of files and logs.

## 2. Install and run a harness

Install once under your user account, without sudo. The installers download
executable code; use administrator-approved versions for qualification and
record `--version`. Start a new shell if the installer changes your PATH.

### Claude Code — native Anthropic Messages

```console
curl -fsSL https://claude.ai/install.sh | bash
claude --version
read -r -p 'Accepted Anthropic model ID: ' MODEL
```

```console
unset ANTHROPIC_API_KEY
export ANTHROPIC_BASE_URL="$PRAXIS_URL"
export ANTHROPIC_AUTH_TOKEN="$PRAXIS_CALLER_JWT"
claude --model "$MODEL"
```

The gateway needs an Anthropic provider key for this path. An OpenAI key alone
does not enable Claude Code; this configuration does not translate APIs.

### Codex — native OpenAI Responses

```console
curl -fsSL https://chatgpt.com/codex/install.sh | sh
codex --version
read -r -p 'Accepted OpenAI Responses model ID: ' MODEL
```

```console
codex \
  -c 'model_provider="praxis"' \
  -c 'model_providers.praxis.name="Praxis"' \
  -c "model_providers.praxis.base_url=\"$PRAXIS_URL/v1\"" \
  -c 'model_providers.praxis.env_key="PRAXIS_CALLER_JWT"' \
  -c 'model_providers.praxis.wire_api="responses"' \
  --model "$MODEL"
```

These [custom-provider settings](https://learn.chatgpt.com/docs/config-file/config-reference)
apply to this invocation. The token is read from the environment, not placed
in the command line. Use a provider/model supporting the required Responses
conversation state; the gateway does not supply translation storage here.

### OpenCode — native Chat Completions

```console
curl -fsSL https://opencode.ai/install | bash
opencode --version
read -r -p 'Accepted Chat Completions model ID: ' MODEL
```

```console
export OPENCODE_CONFIG_CONTENT="$(jq -n --arg model "$MODEL" --arg url "$PRAXIS_URL/v1" '{
  model: ("praxis/" + $model),
  enabled_providers: ["praxis"],
  provider: {
    praxis: {
      npm: "@ai-sdk/openai-compatible",
      name: "Praxis",
      options: {baseURL: $url, apiKey: "{env:PRAXIS_CALLER_JWT}"},
      models: {($model): {name: $model}}
    }
  }
}')"
opencode
```

The [configuration](https://opencode.ai/docs/config/) references the JWT
environment variable; it does not embed its value in a project file.

## Disconnect, renew and stop

The gateway survives your logout. The harness follows your client machine's
normal lifecycle: resume a saved session using its own resume command, or
use `tmux` on a remote client host if the running process must survive SSH
disconnect. Gateway JWT authentication does not retain harness processes.

On `401`, obtain a replacement JWT and restart the harness with the new value.
On `429`, the shared quota or request-rate protection may be exhausted; do not
bypass the gateway with a personal provider login.

When finished, close the harness and clear its caller credentials:

```console
unset PRAXIS_CALLER_JWT ANTHROPIC_AUTH_TOKEN OPENCODE_CONFIG_CONTENT
```
