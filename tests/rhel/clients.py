#!/usr/bin/env python3
"""Manual and automated harnesses must select identical provider/API paths."""
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/common"))
import harness
from harness import configuration


class ClientsTest(unittest.TestCase):
    def test_claude_gateway_launch_clears_inherited_cloud_provider_selectors(self):
        with patch.dict(os.environ, {"CLAUDE_CODE_USE_BEDROCK": "1", "CLAUDE_CODE_USE_VERTEX": "1"}), \
             patch.object(sys, "argv", ["praxis-harness", "claude", "--model", "qwen3-8b"]), \
             patch.object(os, "execvpe") as execute:
            harness.main()
        environment = execute.call_args.args[2]
        self.assertFalse(any(key.startswith("CLAUDE_CODE_USE_") for key in environment))
        self.assertEqual(environment["ANTHROPIC_BASE_URL"], "http://127.0.0.1:8081/vllm")

    def test_print_config_redacts_remote_caller_in_nested_opencode_json(self):
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / "caller.jwt"
            token.write_text("private.caller.signature")
            result = subprocess.run([sys.executable, str(Path(harness.__file__)), "opencode",
                "--model", "qwen3.8-27b-int4", "--url", "https://gateway.test:8443",
                "--token-file", str(token), "--print-config"], capture_output=True, text=True,
                env={**os.environ, "HOME": directory}, check=True)
            self.assertNotIn(token.read_text(), result.stdout + result.stderr)
            selected = json.loads(result.stdout)
            config = json.loads(selected["environment"]["OPENCODE_CONFIG_CONTENT"])
            self.assertEqual(config["provider"]["praxis"]["options"]["apiKey"], "[caller]")

    def test_qwen_menu_configuration_uses_exact_served_id_and_limits(self):
        for model, context in (("qwen3-8b", 16384), ("qwen3.8-27b-int4", 32768)):
            with self.subTest(model=model), tempfile.TemporaryDirectory() as directory:
                path = harness.write_codex_catalog(model, Path(directory))
                entry, = json.loads(path.read_text())["models"]
                self.assertEqual(entry["slug"], model)
                self.assertEqual(entry["visibility"], "list")
                self.assertEqual(entry["context_window"], context)
                self.assertEqual(entry["max_context_window"], context)
                self.assertEqual(entry["input_modalities"], ["text"])
                self.assertEqual(entry["default_reasoning_level"], "medium")
                self.assertEqual([r["effort"] for r in entry["supported_reasoning_levels"]], ["medium"])
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                command, _ = configuration("codex", "vllm", model, "http://localhost:8080", "caller",
                                           catalog_path=path)
                self.assertIn("model_catalog_json=" + json.dumps(str(path)), command)
                self.assertIn('model_reasoning_effort="medium"', command)
            _, env = configuration("claude", "vllm", model, "http://localhost:8081", "caller")
            self.assertEqual(env["ANTHROPIC_CUSTOM_MODEL_OPTION"], model)
            self.assertEqual(env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"], "0")

    def test_gateway_discovery_is_an_explicit_claude_capability(self):
        _, env = configuration("claude", "anthropic", "claude-model", "http://localhost:8081", "caller",
                               gateway_discovery=True)
        self.assertEqual(env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"], "1")
        for name in ("codex", "opencode"):
            with self.assertRaisesRegex(ValueError, "Claude"):
                configuration(name, "vllm", "qwen3-8b", "http://localhost:8080", "caller",
                              gateway_discovery=True)

    def test_qwen38_claude_uses_an_accepted_effort_without_disabling_thinking(self):
        for prompt in (None, "task"):
            command, env = configuration("claude", "vllm", "qwen3.8-27b-int4",
                                         "http://127.0.0.1:8081", "caller", prompt=prompt)
            self.assertIn("--effort", command)
            self.assertEqual(command[command.index("--effort") + 1], "medium")
            self.assertNotIn("CLAUDE_CODE_DISABLE_THINKING", env)
        for provider, model in (("vllm", "qwen3-8b"), ("anthropic", "claude-model")):
            command, _ = configuration("claude", provider, model, "http://127.0.0.1:8081", "caller")
            self.assertNotIn("--effort", command)

    def test_qwen_context_and_output_limits_do_not_override_cloud_models(self):
        for provider in ("vllm", "openai"):
            command, _ = configuration("codex", provider, "model", "http://127.0.0.1:8080", "caller")
            self.assertEqual("model_context_window=16384" in command, provider == "vllm")
            self.assertEqual("model_auto_compact_token_limit=12288" in command, provider == "vllm")
            self.assertEqual("show_raw_agent_reasoning=true" in command, provider == "vllm")
        for provider in ("vllm", "anthropic"):
            _, env = configuration("claude", provider, "model", "http://127.0.0.1:8081", "caller")
            if provider == "vllm":
                self.assertEqual(env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"], "16384")
                self.assertEqual(env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"], "4096")
            else:
                self.assertNotIn("CLAUDE_CODE_MAX_OUTPUT_TOKENS", env)
            self.assertNotIn("CLAUDE_CODE_DISABLE_THINKING", env)

    def test_model_budgets_apply_to_each_harness_and_launch_mode(self):
        for model, context, output in (("qwen3-8b", 16384, 4096),
                                       ("qwen3.8-27b-int4", 32768, 8192)):
            for prompt in (None, "task"):
                with self.subTest(model=model, prompt=prompt):
                    command, _ = configuration("codex", "vllm", model,
                                               "http://127.0.0.1:8080", "caller", prompt=prompt)
                    self.assertIn(f"model_context_window={context}", command)
                    self.assertIn(f"model_auto_compact_token_limit={context - output}", command)
                    _, env = configuration("opencode", "vllm", model,
                                           "http://127.0.0.1:8080", "caller", prompt=prompt)
                    selected = json.loads(env["OPENCODE_CONFIG_CONTENT"])["provider"]["praxis"]["models"][model]
                    self.assertEqual(selected["limit"], {"context": context, "output": output})
                    _, env = configuration("claude", "vllm", model,
                                           "http://127.0.0.1:8081", "caller", prompt=prompt)
                    self.assertEqual(env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"], str(context))
                    self.assertEqual(env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"], str(output))
                    self.assertEqual(env["CLAUDE_CODE_DISABLE_1M_CONTEXT"], "1")

        # The served alias alone must not select local budgets on a cloud route.
        for name, provider in (("codex", "openai"), ("opencode", "openai"),
                               ("opencode", "anthropic"), ("claude", "anthropic")):
            with self.subTest(harness=name, provider=provider):
                command, env = configuration(name, provider, "qwen3.8-27b-int4",
                                             "http://127.0.0.1:8080", "caller")
                self.assertNotIn("model_context_window=32768", command)
                self.assertNotIn("CLAUDE_CODE_MAX_CONTEXT_TOKENS", env)
                self.assertNotIn("CLAUDE_CODE_DISABLE_1M_CONTEXT", env)
                if name == "opencode":
                    selected = json.loads(env["OPENCODE_CONFIG_CONTENT"])["provider"]["praxis"]["models"]["qwen3.8-27b-int4"]
                    self.assertEqual(selected["limit"], {"context": 128000, "output": 4096})

    def test_qwen_reasoning_capability_and_continuation_are_explicit(self):
        for provider in ("vllm", "openai", "anthropic"):
            command, env = configuration("opencode", provider, "qwen3-8b", "http://127.0.0.1:8080", "caller", prompt="task")
            model = json.loads(env["OPENCODE_CONFIG_CONTENT"])["provider"]["praxis"]["models"]["qwen3-8b"]
            if provider == "vllm":
                self.assertTrue(model["reasoning"])
                self.assertEqual(model["interleaved"], {"field": "reasoning"})
                self.assertIn("--thinking", command)
            else:
                self.assertNotIn("interleaved", model)

    def test_interactive_launch_preserves_native_tool_policy_and_smoke_is_bounded(self):
        for prompt in (None, "task"):
            _, env = configuration("opencode", "vllm", "qwen3-8b", "http://127.0.0.1:8080", "caller", prompt=prompt)
            config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
            if prompt:
                self.assertEqual(config["permission"]["bash"]["*"], "deny")
                self.assertEqual(config["agent"]["build"]["steps"], 12)
            else:
                self.assertNotIn("permission", config)
                self.assertNotIn("agent", config)

    def test_qwen_uses_explicit_path_and_caller_not_provider_credentials(self):
        for name in ("codex", "opencode", "claude"):
            command, env = configuration(name, "vllm", "qwen3-8b", "https://gateway:8443", "caller", prompt="task")
            material = " ".join(command) + json.dumps(env)
            self.assertIn("https://gateway:8443/vllm", material)
            self.assertIn("qwen3-8b", material)
            self.assertNotIn("api.openai.com", material)
            self.assertNotIn("api.anthropic.com", material)
            self.assertNotIn("dangerously-skip", material)
            if name == "opencode":
                self.assertEqual(json.loads(env["OPENCODE_CONFIG_CONTENT"])["agent"]["build"]["steps"], 12)

    def test_anthropic_opencode_uses_messages_sdk_and_jwt_authorization(self):
        _, env = configuration("opencode", "anthropic", "fixture", "https://gateway:8443", "caller", prompt="task")
        config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
        self.assertEqual(config["provider"]["praxis"]["npm"], "@ai-sdk/anthropic")
        self.assertEqual(config["provider"]["praxis"]["options"]["headers"]["Authorization"], "Bearer caller")

    def test_unsupported_protocol_pairs_fail_before_starting_cli(self):
        for name, provider in (("codex", "anthropic"), ("claude", "openai")):
            with self.assertRaises(ValueError):
                configuration(name, provider, "fixture", "http://127.0.0.1:8080", "placeholder")


if __name__ == "__main__":
    unittest.main()
