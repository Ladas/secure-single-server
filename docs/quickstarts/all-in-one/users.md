# User setup and usage

The administrator [creates your login](accounts.md), installs Praxis and
configures the available providers. Sign in as your own ordinary account.
Every command here runs without sudo. Provider keys stay in Praxis; clients
use a non-secret placeholder.

## 1. Connect

Skip this step if already logged in. From your workstation, use the login
provided by the administrator and your configured SSH key/agent:

```console
printf 'Your RHEL login (user@host): '
IFS= read -r RHEL_USER_HOST
ssh -o ForwardAgent=no "$RHEL_USER_HOST"
```

The remaining commands run on RHEL as that user.

## 2. Install the approved harnesses

The account helper publishes the tested version list and `praxis-harness`.
Install the CLIs into your own home, once per account:

```console
python3 - <<'PYCLIENT'
import json, pathlib, subprocess
versions = json.loads(pathlib.Path("/usr/local/share/praxis/harness-versions.json").read_text())
subprocess.run(["npm", "install", "--global", "--prefix", str(pathlib.Path.home() / ".local"),
                *[f"{name}@{version}" for name, version in versions.items()]], check=True)
PYCLIENT
export PATH="$HOME/.local/bin:$PATH"
codex --version
opencode --version
claude --version
```

Repeat the PATH export in a new shell. The administrator installs missing host
packages; do not use sudo for npm or a harness. Open your project directory
before starting a client:

```console
mkdir -p ~/projects/praxis-example
cd ~/projects/praxis-example
git init -q
```

## 3. Choose an enabled provider

### Qwen through local vLLM

When installed by the administrator, Qwen needs no cloud credentials. Start
with the qualified OpenCode path:

```console
praxis-harness opencode --provider vllm
```

The launcher selects `qwen3-8b` through Praxis's `/vllm/v1` route. CPU/GPU
OpenCode tool smoke tests passed. Codex and Claude Code currently fail against
the pinned vLLM backend; their reproduction commands and exact results are in
the [compatibility matrix](../../testing/compatibility.md) and
[testing guide](../../testing/harnesses.md#qwen).

### OpenAI

The administrator must [enable OpenAI](../../testing/rhel-real.md#3-add-openai-to-existing-praxis)
and provide a model ID available to that account:

```console
printf 'Approved OpenAI model ID: '
IFS= read -r OPENAI_MODEL
```

Choose either client:

```console
praxis-harness codex --provider openai --model "$OPENAI_MODEL"
```

```console
praxis-harness opencode --provider openai --model "$OPENAI_MODEL"
```

### Anthropic

The administrator can [enable Anthropic independently](../../testing/rhel-real.md#4-add-anthropic-independently).
Choose an approved model, then either client:

```console
printf 'Approved Anthropic model ID: '
IFS= read -r ANTHROPIC_MODEL
```

```console
praxis-harness claude --provider anthropic --model "$ANTHROPIC_MODEL"
```

```console
praxis-harness opencode --provider anthropic --model "$ANTHROPIC_MODEL"
```

Cloud routes passed mock tests; real account/model acceptance remains a
[manual check](../../testing/harnesses.md). Interactive clients keep their
normal tool approvals. Cloud calls use the administrator's provider account.
The launcher configures each native API; it does not enable API translation.

For an installed Switchyard profile, OpenCode can use its Chat listener by
adding `--url http://127.0.0.1:8082` to the OpenAI command. The administrator
controls judge/Weak/Strong routing; Codex Responses and Claude Messages cannot
use that Chat-only listener.

## 4. Optional sandbox execution

Use [OpenShell setup and usage](../../testing/openshell-manual.md) after the
administrator installs the addon. Run its client commands as this same ordinary
user. Sandbox/provider coverage is separate from direct-host coverage; see
[the execution matrix](../../testing/compatibility.md#execution-modes).

## Continue after disconnecting

Normal CLI processes may end when SSH disconnects; use the CLI's resume
facility where available. For a terminal that stays attached to its process,
start the harness inside tmux:

```console
tmux new-session -s coding-task
```

Detach with Ctrl-b, then d. After reconnecting:

```console
tmux attach-session -t coding-task
```

The administrator can install tmux if absent. OpenShell sandbox lifetime does
not by itself guarantee that an interactive CLI session survives disconnects
or that a deleted sandbox's workspace is retained.
