# Harness configuration through Praxis

Use [all-in-one user setup](../all-in-one/users.md) or
[remote client setup](../remote-gateway/users.md) for normal use. This reference
explains the installed `praxis-harness` launcher and file-based alternatives.
It configures the selected CLI; Praxis is the server handling inference.

## Native files or the launcher

For ongoing use, configure the CLI's files and launch the CLI directly. The
`praxis-harness` helper is optional: it supplies per-launch provider settings,
known Qwen limits, environment cleanup and bounded smoke-test options without
rewriting your usual configuration. Its source is `scripts/common/harness.py`,
installed as `/usr/local/bin/praxis-harness` by `scripts/common/harness-user`.

| CLI menu | Where the list comes from | Switching limits |
| --- | --- | --- |
| Codex `/model` | Bundled catalog or a configured `model_catalog_json` | Entries must work at the selected provider's Responses URL; changing the provider connection needs a new launch |
| OpenCode `/models` | Configured `provider.NAME.models` entries | Multiple configured provider/model pairs can coexist in one session |
| Claude Code `/model` | Configured picker entries; optional native gateway discovery | One Messages base per launch; discovery filters out IDs without `claude`/`anthropic`, so configure Qwen explicitly |

A model menu does not install weights, enforce a gateway allowlist, prove account
access, or combine gateway catalogs. Give each harness the exact served IDs and
appropriate context limits. The helper currently supplies one selected local
model; persistent files are the better choice for a maintained multi-model menu.

| Provider | Codex | OpenCode | Claude Code |
| --- | --- | --- | --- |
| vLLM | Responses, `:8080/vllm/v1` | Chat Completions, `:8080/vllm/v1` | Messages, `:8081/vllm` base |
| OpenAI | Responses, `:8080/v1` | Chat Completions, `:8080/v1` | Not configured |
| Anthropic | Not configured | Messages, `:8081/v1` | Messages, `:8081` base |

These are loopback origins on an all-in-one host. Claude appends `/v1/messages`
to its base. Remote mode replaces the origin with the HTTPS gateway for every
API, retaining the provider path. The launcher does not enable API translation.
Local clients use `local-placeholder`; remote clients use a caller JWT. Upstream
provider keys stay with Praxis.

The examples below target **27B after the server is updated to 32,768 tokens**.
For 8B, use `qwen3-8b`, context 16,384, output 4,096 and Codex compaction 12,288.
Thinking consumes output tokens. See [preset limits](vllm.md#requirements).
Merge file settings deliberately with existing configuration. Native files do not
inherit future launcher fixes; verify menu selection and a tool query after editing.

## Codex

<details>
<summary>Expand: per-launch flags, TOML alternative and model menu</summary>

```console
praxis-harness codex --provider vllm --model qwen3.8-27b-int4
```

The launcher selects a custom `praxis` provider with the Responses wire API,
passes `--model`, disables web search, and selects the `workspace-write`
sandbox. It sets context to 32,768 and auto-compaction to 24,576, and enables
raw reasoning display. The 8,192-token difference is headroom, not an enforced
generation cap. Normal interactive approvals remain active.
For Qwen, the generated catalog contains the selected model with matching
context limits, medium reasoning and a concise coding instruction template.

To maintain these settings in `~/.codex/config.toml` instead:

```toml
model = "qwen3.8-27b-int4"
model_provider = "praxis"
model_context_window = 32768
model_auto_compact_token_limit = 24576
model_reasoning_effort = "medium"
show_raw_agent_reasoning = true
web_search = "disabled"
sandbox_mode = "workspace-write"

[model_providers.praxis]
name = "Praxis"
base_url = "http://127.0.0.1:8080/vllm/v1"
env_key = "PRAXIS_PLACEHOLDER_KEY"
wire_api = "responses"
```

Then launch directly:

```console
PRAXIS_PLACEHOLDER_KEY=local-placeholder codex
```

The helper's `-c` overrides select these settings for that launch without
rewriting the TOML file. Neither `--model` nor the TOML `model` key adds an
entry to `/model`. The helper now passes `model_catalog_json` for local Qwen.
Inspect its generated path with:

```console
praxis-harness codex --provider vllm --model qwen3.8-27b-int4 --print-config
```

For the file alternative, add `model_catalog_json = "/absolute/path/to/catalog.json"`
using that generated catalog or a maintained copy. It is read at startup.
Keep caller credentials out of the catalog.
[Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

</details>

## OpenCode

<details>
<summary>Expand: environment JSON, config-file alternative and model menu</summary>

```console
praxis-harness opencode --provider vllm --model qwen3.8-27b-int4
```

The launcher supplies `OPENCODE_CONFIG_CONTENT` with a `praxis` provider, one
selected model and its limits. Qwen uses the OpenAI-compatible Chat SDK, with
reasoning enabled and interleaved reasoning preserved for tool continuation.
Anthropic instead uses `@ai-sdk/anthropic` and the Messages listener.

For a file alternative, save the following as a dedicated user-owned file,
for example `~/.config/praxis/opencode-qwen38.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "praxis/qwen3.8-27b-int4",
  "provider": {
    "praxis": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Praxis",
      "options": {
        "baseURL": "http://127.0.0.1:8080/vllm/v1",
        "apiKey": "local-placeholder",
        "headers": {"Authorization": "Bearer local-placeholder"}
      },
      "models": {
        "qwen3.8-27b-int4": {
          "name": "qwen3.8-27b-int4",
          "limit": {"context": 32768, "output": 8192},
          "reasoning": true,
          "interleaved": {"field": "reasoning"}
        }
      }
    }
  }
}
```

Start it with:

```console
OPENCODE_CONFIG="$HOME/.config/praxis/opencode-qwen38.json" opencode
```

Alternatively merge it into the normal user `~/.config/opencode/opencode.json`
or project `opencode.json`. OpenCode merges configuration sources; an existing
`OPENCODE_CONFIG_CONTENT` can take precedence over a file. The launcher does not
set an explicit compaction trigger: OpenCode uses its context/output settings
and compaction configuration. `/models` displays the configured Praxis entry;
this is not evidence of discovery from the gateway.
[OpenCode configuration](https://opencode.ai/docs/config/).

</details>

## Claude Code

<details>
<summary>Expand: environment and flags, settings-file alternative and model menu</summary>

```console
praxis-harness claude-code --provider vllm --model qwen3.8-27b-int4
```

The launcher sets the Messages base and local authentication, maps the Opus,
Sonnet and Haiku aliases to Qwen, and passes the selected model explicitly.
For local Qwen it selects `--permission-mode default` (Manual) so tool execution
uses user approval rather than the unavailable auto-mode classifier.
For 27B it selects `--effort medium`; thinking remains enabled. It supplies a
32,768-token context and 8,192-token output limit and disables 1M context variants
so a menu alias cannot override the served limit. Compaction follows Claude's
client logic; this is not a separately configured 24,576-token trigger.

Local Qwen also uses `CLAUDE_CODE_SIMPLE=1`: a reduced system prompt and basic
file/shell tools, with automatic `CLAUDE.md`, skill, plugin, hook and subagent
discovery disabled. This affects repository workflows; it is not full Claude
Code feature qualification. Nonessential traffic and experimental betas are
disabled. The native Anthropic route does not apply these Qwen-specific settings.

A dedicated file such as `~/.config/praxis/claude-qwen38.json` can hold the
model and environment settings:

```json
{
  "model": "qwen3.8-27b-int4",
  "env": {
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:8081/vllm",
    "ANTHROPIC_API_KEY": "local-placeholder",
    "ANTHROPIC_AUTH_TOKEN": "local-placeholder",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "qwen3.8-27b-int4",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "qwen3.8-27b-int4",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "qwen3.8-27b-int4",
    "ANTHROPIC_CUSTOM_MODEL_OPTION": "qwen3.8-27b-int4",
    "ANTHROPIC_CUSTOM_MODEL_OPTION_NAME": "qwen3.8-27b-int4",
    "ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION": "Local Qwen through Praxis",
    "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "0",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
    "CLAUDE_CODE_DISABLE_1M_CONTEXT": "1",
    "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "32768",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "8192"
  }
}
```

Launch with simple mode already in the process environment:

```console
CLAUDE_CODE_SIMPLE=1 claude --settings "$HOME/.config/praxis/claude-qwen38.json" \
  --model qwen3.8-27b-int4 --effort medium --permission-mode default
```

`ANTHROPIC_CUSTOM_MODEL_OPTION` adds the exact Qwen ID to the picker.
Managed `availableModels` restrictions still apply. `--gateway-model-discovery`
opts into Claude's native discovery; it is disabled by default and filters out
Qwen IDs. For remote gateways with both clouds, the shared model-list route
returns OpenAI's catalog, so use configured Claude entries there.
[Claude settings](https://code.claude.com/docs/en/settings),
[environment variables](https://code.claude.com/docs/en/env-vars) and
[gateway discovery](https://code.claude.com/docs/en/llm-gateway-protocol#model-discovery).

</details>

## Additional compatible providers

[Enable the provider on the server](providers.md#another-compatible-provider),
then configure its route in the native CLI files above. For provider `team`:

| Client | Local base URL |
| --- | --- |
| Codex / OpenCode OpenAI-compatible | `http://127.0.0.1:8080/providers/team/v1` |
| Claude Code | `http://127.0.0.1:8081/providers/team` |
| OpenCode Anthropic | `http://127.0.0.1:8081/providers/team/v1` |

For a quick single-model launch without file edits:

```console
praxis-harness codex --provider openai --route-prefix /providers/team --model MODEL_ID
praxis-harness opencode --provider openai --route-prefix /providers/team --model MODEL_ID
praxis-harness claude-code --provider anthropic --route-prefix /providers/team --model MODEL_ID
```

Here `--provider` selects the API dialect; `--route-prefix` selects the upstream
provider configured in Praxis. A hosted Qwen model can need model-specific context,
reasoning and permission settings; do not assume the local-vLLM preset matches it.

To maintain several OpenCode providers, add separately named entries under
`provider`, each with its URL and `models` map. Use distinct custom IDs such as `praxis-local`,
`praxis-openai` and `praxis-team` (built-in IDs can merge extra catalog entries); `/models` can then switch among their entries. For Codex,
maintain a catalog per Responses connection and select that connection at launch.

For Claude, add non-Claude models explicitly to its settings file:

```json
{
  "modelPicker": {
    "options": [{"model": "EXACT_SERVED_ID", "label": "Hosted model"}]
  }
}
```

Its built-in aliases can still appear. Configure only models supported by the
selected Messages endpoint. `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` is
optional and does not discover arbitrary Qwen IDs. A second Messages endpoint
needs a separate settings file and launch, not another model-picker label.

## Remote and automated use

For HTTPS, the launcher requires `--token-file` with a caller JWT and accepts
`--ca-file` for the gateway CA. It passes CA trust through `SSL_CERT_FILE` and
`NODE_EXTRA_CA_CERTS`. A file-based setup needs the same origin, provider path,
caller authentication and CA trust. Keep tokens in private user storage or
environment references supported by the client, never in committed project
files. No TLS verification bypass is needed.

The launcher removes inherited `OPENAI_*`, `ANTHROPIC_*` and `PRAXIS_*`
environment values and Claude's `CLAUDE_CODE_USE_*` cloud selectors before adding
its own settings, keeping Claude on the Messages gateway route. Launching a CLI directly does not
provide that cleanup; check for conflicting provider/authentication settings.
`--print-config` prints the command and generated environment with the caller
credential replaced by `[caller]`; it starts no CLI. It is an inspection aid,
not a complete runnable configuration export.

`--prompt` changes execution mode: Codex uses ephemeral JSON `exec`, OpenCode
uses JSON `run` with bounded build steps and tool permissions, and Claude uses
streamed JSON print mode with a turn limit and restricted tools. These smoke
settings are distinct from normal interactive approvals. See
[manual acceptance](../../testing/harnesses.md).
