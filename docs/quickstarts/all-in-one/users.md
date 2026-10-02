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

The [account helper](accounts.md) installs `praxis-harness-config` and the tested
CLI version list. Provider credentials remain on the server.

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

## 3. Configure and run the native harnesses

For an administrator-configured [unified catalog](../common/providers.md#unified-models-all-in-one),
run once, and again after changing enabled providers or allowed models:

```console
praxis-harness-config
```

This reads both local `/v1/models` catalogs and writes private user files, with
backups of changed files. Both API catalogs need at least one enabled model;
Qwen alone supplies both. No config-home environment override is needed.
Start one CLI from your project:

```console
codex --profile praxis
```

```console
claude-code
```

```console
opencode
```

`claude-code` is a user-owned symlink to the installed `claude` executable.

| Harness | Menu | Generated configuration |
| --- | --- | --- |
| Codex | `/model`: Responses models | `~/.codex/praxis.config.toml`, `~/.codex/model-catalogs/praxis.json` |
| Claude Code | `/model`: Messages models | `~/.claude/settings.json` |
| OpenCode | `/models`: both APIs | `~/.config/opencode/opencode.json` |

The menus are snapshots of the gateway's configured aliases, such as
`vllm/qwen3.8-27b-int4` or `openai/<approved-model>`. They do not automatically
import upstream catalogs. Refresh and restart the harness after admin changes.
For Codex, `--profile praxis` loads the generated
[named profile](https://learn.chatgpt.com/docs/config-file/config-advanced#profiles).

OpenCode uses just two active provider entries: `praxis-openai` at
`http://127.0.0.1:8080/v1` and `praxis-messages` at `http://127.0.0.1:8081/v1`.
GPT and local Qwen use Responses under `praxis-openai`; other compatible models
may use Chat. `/models` can switch between these entries within one session.
An optional `--model` chooses the starting entry; it does not lock the API.
Existing unrelated provider definitions are preserved but excluded by
`enabled_providers`. A fresh account has only the two Praxis entries.

### Verify a model, then switch

Ask the selected model:

> Create add.py with add(a, b), write tests for positive, negative and zero
> inputs, run python3 -m unittest -v, and report the actual result.

Approve the tool calls and inspect the resulting files/tests. Repeat after
selecting another model, then switch back. Menu visibility alone does not prove
inference, tool use or history compatibility.

The pinned vLLM rejects cloud encrypted reasoning when returning to Qwen
**Responses**. The normal commands above do not include a history adapter.
Use a fresh Qwen session, or use Qwen's Messages entry in OpenCode/Claude Code.
Do not assume a long cloud conversation fits Qwen's smaller context.

Limits come from the approved catalog. Codex/OpenCode use per-model context;
Codex's compaction headroom does not enforce an output cap. Claude's context
override covers unknown model IDs; recognized Claude models retain their own
window. Long-history compaction and downsizing need qualification.
Claude runs in simple/Manual mode for Qwen compatibility: approve tools yourself;
automatic skill/plugin discovery and the auto-mode classifier are not qualified.

On `429`, stop repeated retries and ask the administrator to
[inspect the quota and request throttle](../common/token-quotas.md#read-accounting-and-identify-a-429).

### Gateways without a unified catalog

Use [the per-provider launcher or native-file examples](../common/harness-configuration.md)
for legacy all-in-one or Switchyard installations. `praxis-harness` is defined
in `scripts/common/harness.py` and installed as `/usr/local/bin/praxis-harness`.
It supplies settings for one launch; it is unnecessary after generating the
unified native files above. Provider-specific `/vllm` and `/providers/NAME`
routes are replaced when unified mode is enabled.

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
