#!/usr/bin/env python3
"""Start a native harness through Praxis, using only a placeholder or caller JWT."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit


def qwen_limits(model):
    """Match the served context in scripts/vllm/install, not the native maximum."""
    return (32768, 8192) if model == "qwen3.8-27b-int4" else (16384, 4096)


def write_codex_catalog(model, directory):
    """Pinned Codex 0.157.1 ModelsResponse; only the explicitly selected preset."""
    context, output = qwen_limits(model)
    catalog = {"models": [{"slug": model, "display_name": model, "description": "Local Qwen through Praxis",
        "model_messages": {"instructions_template": "You are a coding assistant working in the user's repository. "
            "Follow the user's instructions and applicable repository guidance. Inspect relevant files before editing. "
            "Use the supplied tools to make focused changes, preserve unrelated work, and run appropriate checks. "
            "Report what changed, what you verified, and any unresolved limitations. Do not claim a tool action or "
            "test succeeded unless its result confirms it."},
        "default_reasoning_level": "medium",
        "supported_reasoning_levels": [{"effort": "medium", "description": "Thinking enabled through vLLM"}],
        "shell_type": "unified_exec", "visibility": "list",
        "supported_in_api": True, "priority": 1, "support_verbosity": False,
        "default_reasoning_summary": "none", "supports_reasoning_summary_parameter": False,
        "truncation_policy": {"mode": "tokens", "limit": 4096},
        "context_window": context, "max_context_window": context, "auto_compact_token_limit": context - output,
        "experimental_supported_tools": [], "input_modalities": ["text"]}]}
    data = (json.dumps(catalog, indent=2) + "\n").encode()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / ("codex-" + hashlib.sha256(data).hexdigest()[:16] + ".json")
    fd, temporary = tempfile.mkstemp(dir=directory, prefix=".catalog-")
    try:
        with os.fdopen(fd, "wb") as target:
            target.write(data)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return path.resolve()


def configuration(name, provider, model, base, caller, *, prompt=None, messages_base=None,
                  catalog_path=None, gateway_discovery=False):
    name = "claude" if name == "claude-code" else name
    if gateway_discovery and name != "claude":
        raise ValueError("native gateway discovery is a Claude option; Codex/OpenCode use configured catalogs")
    if (name, provider) in (("codex", "anthropic"), ("claude", "openai")):
        raise ValueError("this harness requires a different native API; no provider translation is configured")
    context, output = qwen_limits(model) if provider == "vllm" else (128000, 4096)
    base = base.rstrip("/")
    messages_base = (messages_base or base).rstrip("/")
    if provider == "vllm":
        base += "/vllm"
        messages_base += "/vllm"
    env = {"PRAXIS_PLACEHOLDER_KEY": caller}
    if name == "codex":
        command = ["codex", *(["exec", "--json", "--ephemeral"] if prompt else []),
            "--sandbox", "workspace-write", "-c", 'model_provider="praxis"',
            "-c", 'model_providers.praxis.name="Praxis"',
            "-c", 'model_providers.praxis.base_url=' + json.dumps(base + "/v1"),
            "-c", 'model_providers.praxis.env_key="PRAXIS_PLACEHOLDER_KEY"',
            "-c", 'model_providers.praxis.wire_api="responses"', "-c", 'web_search="disabled"', "--model", model]
        if provider == "vllm":
            command += ["-c", f"model_context_window={context}",
                        "-c", f"model_auto_compact_token_limit={context - output}",
                        "-c", 'model_reasoning_effort="medium"',
                        "-c", "show_raw_agent_reasoning=true"]
            if catalog_path:
                command += ["-c", "model_catalog_json=" + json.dumps(str(catalog_path))]
    elif name == "opencode":
        anthropic = provider == "anthropic"
        config = {"model": "praxis/" + model,
            "provider": {"praxis": {"npm": "@ai-sdk/anthropic" if anthropic else "@ai-sdk/openai-compatible", "name": "Praxis",
                "options": {"baseURL": (messages_base if anthropic else base) + "/v1", "apiKey": caller,
                            "headers": {"Authorization": "Bearer " + caller}},
                "models": {model: {"name": model, "limit": {"context": context, "output": output}}}}}}
        if provider == "vllm":
            config["provider"]["praxis"]["models"][model].update(
                reasoning=True, interleaved={"field": "reasoning"})
        if prompt:
            config.update(agent={"build": {"steps": 12}}, permission={
                "*": "deny", "read": "allow", "edit": "allow",
                "bash": {"*": "deny", "python3 *": "allow"}})
        env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
        command = ["opencode", *(["run", "--format", "json"] if prompt else [])]
        if prompt and provider == "vllm":
            command += ["--thinking"]
    else:
        env.update(ANTHROPIC_BASE_URL=messages_base, ANTHROPIC_AUTH_TOKEN=caller,
                   CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
                   CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY="1" if gateway_discovery else "0")
        if provider == "vllm":
            env.update(ANTHROPIC_API_KEY=caller, ANTHROPIC_DEFAULT_OPUS_MODEL=model,
                       ANTHROPIC_DEFAULT_SONNET_MODEL=model, ANTHROPIC_DEFAULT_HAIKU_MODEL=model,
                       CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS="1", CLAUDE_CODE_SIMPLE="1",
                       CLAUDE_CODE_DISABLE_1M_CONTEXT="1",
                       ANTHROPIC_CUSTOM_MODEL_OPTION=model, ANTHROPIC_CUSTOM_MODEL_OPTION_NAME=model,
                       ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION="Local Qwen through Praxis",
                       CLAUDE_CODE_MAX_CONTEXT_TOKENS=str(context), CLAUDE_CODE_MAX_OUTPUT_TOKENS=str(output))
        command = ["claude", *(["-p"] if prompt else []), "--model", model]
        if provider == "vllm":
            command += ["--permission-mode", "default"]
        if provider == "vllm" and model == "qwen3.8-27b-int4":
            # This model's template rejects Claude's default "high" effort.
            command += ["--effort", "medium"]
        if prompt:
            command += ["--output-format", "stream-json", "--verbose", "--allowedTools", "Bash(python3 *)",
                        "Read", "Write", "Edit", "--max-turns", "8"]
    if prompt:
        command.append(prompt)
        env["CI"] = "1"
    return command, env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("harness", choices=("codex", "opencode", "claude-code", "claude"),
                        help="Claude Code: use claude-code (claude remains an alias)")
    parser.add_argument("--provider", choices=("vllm", "openai", "anthropic"), default="vllm")
    parser.add_argument("--model", help="Qwen defaults to qwen3-8b; cloud models must be selected explicitly")
    parser.add_argument("--url", help="gateway origin, without /v1 or /vllm; defaults to the harness's local listener")
    parser.add_argument("--token-file", type=Path, help="remote caller JWT file, never a provider API key")
    parser.add_argument("--ca-file", type=Path, help="CA certificate for a lab HTTPS gateway")
    parser.add_argument("--prompt", help="noninteractive task; omit to start an interactive session")
    parser.add_argument("--gateway-model-discovery", action="store_true",
                        help="Claude: opt in to native gateway discovery (Qwen IDs are filtered by Claude)")
    parser.add_argument("--print-config", action="store_true", help="print generated settings with caller credentials redacted; do not launch")
    args = parser.parse_args()
    if args.harness == "claude-code":
        args.harness = "claude"
    model = args.model or ("qwen3-8b" if args.provider == "vllm" else None)
    if not model or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", model):
        parser.error("supply an available model ID with --model")
    base = args.url or ("http://127.0.0.1:8081" if args.harness == "claude" or args.provider == "anthropic" else "http://127.0.0.1:8080")
    parsed = urlsplit(base)
    if parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        parser.error("--url must be a gateway origin, without credentials or an API path")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost")):
        parser.error("use HTTPS for a remote gateway or HTTP on loopback")
    if parsed.scheme == "https" and not args.token_file:
        parser.error("remote HTTPS needs --token-file containing a caller JWT")
    caller = args.token_file.read_text().strip() if args.token_file else "local-placeholder"
    if args.token_file and not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", caller):
        parser.error("token file must contain one caller JWT")
    try:
        catalog = (write_codex_catalog(model, Path.home() / ".cache/praxis-harness")
                   if args.harness == "codex" and args.provider == "vllm" else None)
        command, additions = configuration(args.harness, args.provider, model, base, caller, prompt=args.prompt,
                                           catalog_path=catalog, gateway_discovery=args.gateway_model_discovery)
    except ValueError as error:
        parser.error(str(error))
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("OPENAI_", "ANTHROPIC_", "PRAXIS_", "CLAUDE_CODE_USE_"))}
    environment.update(additions)
    if args.ca_file:
        ca = str(args.ca_file.resolve(strict=True))
        environment.update(NODE_EXTRA_CA_CERTS=ca, SSL_CERT_FILE=ca)
        additions.update(NODE_EXTRA_CA_CERTS=ca, SSL_CERT_FILE=ca)
    if args.print_config:
        print(json.dumps({"command": command, "environment": additions}, indent=2).replace(caller, "[caller]"))
        return
    os.execvpe(command[0], command, environment)


if __name__ == "__main__":
    main()
