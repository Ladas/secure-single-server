#!/usr/bin/env python3
"""Manual and automated harnesses must select identical provider/API paths."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/common"))
from harness import configuration


class ClientsTest(unittest.TestCase):
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
