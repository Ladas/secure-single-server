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

The [account helper](../../../scripts/common/harness_user.py) installs
`/usr/local/bin/praxis-harness`, a copy of the
[Python launcher](../../../scripts/common/harness.py), and the tested version list.
The launcher sets the Praxis URL, provider, model and client limits, then starts
the chosen CLI with its normal interactive tool approvals. Run
`praxis-harness --help` to see its options.

<details>
<summary>What the launcher changes, and using a configuration file instead</summary>

`praxis-harness` starts your installed CLI with settings for this launch. It
does not start another proxy or change the model installed on the server.
Codex receives command-line settings, OpenCode receives JSON through
`OPENCODE_CONFIG_CONTENT`, and Claude receives environment variables and flags.
The launcher does not rewrite your configuration files or fetch a combined
provider catalog. The CLI can still load its existing settings.

See the expandable [per-harness configuration examples](../common/harness-configuration.md)
for the exact routes, limits and file-based alternatives. With local Qwen,
Claude uses simple mode: automatic `CLAUDE.md`, skill, plugin and hook discovery
is disabled. Interactive tool approvals remain active.

</details>

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
with OpenCode. Read the single installed model from the gateway:

```console
VLLM_MODEL=$(curl -fsS http://127.0.0.1:8080/vllm/v1/models |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["data"][0]["id"])')
printf 'Model: %s\n' "$VLLM_MODEL"
praxis-harness opencode --provider vllm --model "$VLLM_MODEL"
```

The launcher selects that model through Praxis's `/vllm/v1` route, with thinking
enabled and reasoning separated from the final answer. The 8B preset serves a
16,384-token context with a 4,096-token OpenCode/Claude output budget; 27B uses
32,768 and 8,192 respectively, including thinking. Use the matching updated
server and launcher. The larger 27B budgets still need a RHEL rerun; existing
passes used 16k/4k. Both supplied model presets support these three clients. CPU responses
can take several minutes; GPU is faster for interactive use. Context remains
limited compared with hosted models, and model/tool reliability varies.

Or choose another harness:

```console
praxis-harness codex --provider vllm --model "$VLLM_MODEL"
```

```console
praxis-harness claude --provider vllm --model "$VLLM_MODEL"
```

### OpenAI

The administrator must [enable OpenAI](../common/providers.md#add-openai)
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

The administrator can [enable Anthropic independently](../common/providers.md#add-anthropic).
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

### Model menus

OpenCode uses `/models`; Claude and Codex use `/model`. With these launchers,
OpenCode lists the configured Praxis model and Claude maps its configured Qwen
aliases. Codex's current menu omits Qwen: keep the model selected by
`praxis-harness codex --provider vllm --model "$VLLM_MODEL"`. None of these
commands displays an automatically aggregated inventory of all Praxis providers.
Other built-in entries are not a list of administrator-approved models; use the
supplied IDs.

Interactive clients keep their normal tool approvals. Cloud calls use the administrator's provider account.
The launcher configures each native API; it does not enable API translation.

On `429`, stop repeated retries and ask the administrator to
[check the shared token quota and request throttle](../common/token-quotas.md#read-accounting-and-identify-a-429).

For an installed Switchyard profile, OpenCode can use its Chat listener by
adding `--url http://127.0.0.1:8082` to the OpenAI command. The administrator
controls judge/Weak/Strong routing; Codex Responses and Claude Messages cannot
use that Chat-only listener.

## 4. Optional sandbox execution

OpenShell requires separate authenticated management access. Ordinary-user
enrollment is unfinished; see [OpenShell access status](../openshell-praxis/users.md).
Continue using the direct clients above until that access is available.

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
