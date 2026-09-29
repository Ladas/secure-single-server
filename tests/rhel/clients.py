#!/usr/bin/env python3
"""Manual and automated harnesses must select identical provider/API paths."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/common"))
from harness import configuration


class ClientsTest(unittest.TestCase):
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
