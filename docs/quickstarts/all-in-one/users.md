# User workflow

The administrator must install one of the persistent profiles before
users follow this workflow. Each user signs in with a separate OS account and
runs an approved harness on the RHEL server. The administrator supplies the
login, accepted model IDs, and any required harness version. Users do not need
the deployment bundle, Praxis configuration, or provider credentials.

## Connect to the server

On your laptop, start Bash so the interactive prompts work on both macOS and
Linux:

```console
bash
```

Enter your settings: paste the block below, answer each prompt, and press
Enter. Use your own server account (such as `alice@hostname`) or an SSH alias.
Enter an absolute private-key path without quotes, or leave it blank to use
your SSH configuration or agent. The private key stays on your laptop.

```console
{
  read -r -p 'RHEL user login: ' RHEL_HOST
  read -r -p 'SSH private-key path (Enter for SSH defaults): ' SSH_KEY
}
```

Copy and run unchanged to open a Bash session on RHEL:

```console
SSH_OPTIONS=()
if [[ -n "$SSH_KEY" ]]; then
  SSH_OPTIONS=(-i "$SSH_KEY" -o IdentitiesOnly=yes)
fi
ssh -t "${SSH_OPTIONS[@]}" "$RHEL_HOST" 'bash -l'
```

All remaining commands run under your ordinary RHEL account. If you already
have a Session Manager session for that account, start `bash` there instead.

## Prepare your user session

The host needs `curl`, `tar`, and `gzip`; OpenCode configuration below also
uses `jq`. Ask the administrator to install any missing packages. The harness
installers run without `sudo` and store binaries in your home directory.
They install current releases; skip installation when the administrator has
already supplied an approved version.

Copy and run unchanged after login to make user-installed commands available:

```console
export PATH="$HOME/.local/bin:$HOME/.opencode/bin:$PATH"
```

Choose one harness below and run it from the project directory you want to
work on. Enter settings only in the labeled prompt blocks; the remaining
blocks can be copied unchanged.

| Harness API | Base URL |
| --- | --- |
| OpenAI Responses, including Codex | `http://127.0.0.1:8080/v1` |
| OpenAI Chat Completions | `http://127.0.0.1:8080/v1` |
| Native Anthropic Messages | `http://127.0.0.1:8081` |
| Switchyard Chat Completions, when installed | `http://127.0.0.1:8082/v1` |

The client supplies a non-secret placeholder where it requires an API key.
Praxis removes that value and injects the provider credential only into the
selected upstream request.

## Claude Code

Install once under your user account using the
[official installer](https://code.claude.com/docs/en/setup):

```console
curl -fsSL https://claude.ai/install.sh | bash
claude --version
```

Enter your settings (the model ID supplied by your administrator):

```console
read -r -p 'Accepted Anthropic model ID: ' MODEL
```

Copy and run unchanged to use the native Anthropic listener:

```console
unset ANTHROPIC_API_KEY
export ANTHROPIC_BASE_URL=http://127.0.0.1:8081
export ANTHROPIC_AUTH_TOKEN=local-placeholder
claude --model "$MODEL"
```

The authentication token is a non-secret placeholder; Praxis removes it
before injecting the protected provider credential.
The administrator must have configured an Anthropic key; the OpenAI key used
by the other two workflows does not enable this listener's provider calls.

## Codex

Install once under your user account using the
[official installer](https://learn.chatgpt.com/docs/codex/cli), following any
installer prompts:

```console
curl -fsSL https://chatgpt.com/codex/install.sh | sh
codex --version
```

Enter your settings (the model ID supplied by your administrator):

```console
read -r -p 'Accepted OpenAI Responses model ID: ' MODEL
```

Copy and run unchanged. The [custom-provider
settings](https://learn.chatgpt.com/docs/config-file/config-advanced#custom-model-providers)
apply to this invocation:

```console
export PRAXIS_PLACEHOLDER_KEY=local-placeholder
codex \
  -c 'model_provider="praxis"' \
  -c 'model_providers.praxis.name="Praxis"' \
  -c 'model_providers.praxis.base_url="http://127.0.0.1:8080/v1"' \
  -c 'model_providers.praxis.env_key="PRAXIS_PLACEHOLDER_KEY"' \
  -c 'model_providers.praxis.wire_api="responses"' \
  --model "$MODEL"
```

Codex uses port `8080`; the Switchyard listener is Chat Completions only. The
same provider settings may instead be placed in the user's
`~/.codex/config.toml`.

## OpenCode

Install once under your user account using the
[official installer](https://opencode.ai/docs/):

```console
curl -fsSL https://opencode.ai/install | bash
opencode --version
```

Enter your settings (an accepted Chat Completions model ID):

```console
read -r -p 'Accepted Chat Completions model ID: ' MODEL
```

Copy and run unchanged. `jq` inserts the model ID into the
[runtime configuration](https://opencode.ai/docs/config/) without editing
project files:

```console
export OPENCODE_CONFIG_CONTENT="$(jq -n --arg model "$MODEL" '{
  model: ("praxis/" + $model),
  provider: {
    praxis: {
      npm: "@ai-sdk/openai-compatible",
      name: "Praxis",
      options: {
        baseURL: "http://127.0.0.1:8080/v1",
        apiKey: "local-placeholder"
      },
      models: {
        ($model): {name: "Approved Praxis model"}
      }
    }
  }
}')"
opencode
```

An administrator-managed OpenCode configuration may take precedence over
these user settings. Follow the administrator's model selection in that case.

## Continue after an SSH disconnect

Use one of these workflows:

| Workflow | What happens after disconnect | How to continue |
| --- | --- | --- |
| Normal harness session | The process may end | SSH again, start the harness, and use its resume command, such as `/resume` where supported |
| `tmux` | The same process and terminal continue | SSH again and attach to the session |
| Later OpenShell phase | A managed sandbox retains the harness | Reconnect to the sandbox; no `tmux` is needed |

For `tmux`:

```console
command -v tmux
tmux new-session -s coding-task
```

Start the harness inside that session. Detach with `Ctrl-b`, then `d`.
After reconnecting over SSH, attach to the running session:

```console
tmux attach-session -t coding-task
```

A minimal RHEL installation may not include `tmux`; the administrator can
install the `tmux` package.
