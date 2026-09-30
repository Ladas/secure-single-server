#!/usr/bin/env python3
"""Start a native harness through Praxis, using only a placeholder or caller JWT."""
import argparse
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

QWEN_CONTEXT = 16384
QWEN_OUTPUT = 4096


def configuration(name, provider, model, base, caller, *, prompt=None, messages_base=None):
    if (name, provider) in (("codex", "anthropic"), ("claude", "openai")):
        raise ValueError("this harness requires a different native API; no provider translation is configured")
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
            command += ["-c", f"model_context_window={QWEN_CONTEXT}",
                        "-c", f"model_auto_compact_token_limit={QWEN_CONTEXT - QWEN_OUTPUT}",
                        "-c", "show_raw_agent_reasoning=true"]
    elif name == "opencode":
        anthropic = provider == "anthropic"
        config = {"model": "praxis/" + model,
            "provider": {"praxis": {"npm": "@ai-sdk/anthropic" if anthropic else "@ai-sdk/openai-compatible", "name": "Praxis",
                "options": {"baseURL": (messages_base if anthropic else base) + "/v1", "apiKey": caller,
                            "headers": {"Authorization": "Bearer " + caller}},
                "models": {model: {"name": model, "limit": {"context": QWEN_CONTEXT if provider == "vllm" else 128000,
                                                               "output": QWEN_OUTPUT if provider == "vllm" else 4096}}}}}}
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
                   CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1")
        if provider == "vllm":
            env.update(ANTHROPIC_API_KEY=caller, ANTHROPIC_DEFAULT_OPUS_MODEL=model,
                       ANTHROPIC_DEFAULT_SONNET_MODEL=model, ANTHROPIC_DEFAULT_HAIKU_MODEL=model,
                       CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS="1", CLAUDE_CODE_SIMPLE="1",
                       CLAUDE_CODE_MAX_CONTEXT_TOKENS=str(QWEN_CONTEXT), CLAUDE_CODE_MAX_OUTPUT_TOKENS=str(QWEN_OUTPUT))
        command = ["claude", *(["-p"] if prompt else []), "--model", model]
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
    parser.add_argument("harness", choices=("codex", "opencode", "claude"))
    parser.add_argument("--provider", choices=("vllm", "openai", "anthropic"), default="vllm")
    parser.add_argument("--model", help="Qwen defaults to qwen3-8b; cloud models must be selected explicitly")
    parser.add_argument("--url", help="gateway origin, without /v1 or /vllm; defaults to the harness's local listener")
    parser.add_argument("--token-file", type=Path, help="remote caller JWT file, never a provider API key")
    parser.add_argument("--ca-file", type=Path, help="CA certificate for a lab HTTPS gateway")
    parser.add_argument("--prompt", help="noninteractive task; omit to start an interactive session")
    args = parser.parse_args()
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
        command, additions = configuration(args.harness, args.provider, model, base, caller, prompt=args.prompt)
    except ValueError as error:
        parser.error(str(error))
    environment = {key: value for key, value in os.environ.items() if not key.startswith(("OPENAI_", "ANTHROPIC_", "PRAXIS_"))}
    environment.update(additions)
    if args.ca_file:
        ca = str(args.ca_file.resolve(strict=True))
        environment.update(NODE_EXTRA_CA_CERTS=ca, SSL_CERT_FILE=ca)
    os.execvpe(command[0], command, environment)


if __name__ == "__main__":
    main()
