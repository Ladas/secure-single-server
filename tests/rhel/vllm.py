#!/usr/bin/env python3
"""Mutable RHEL inference must never publish its unauthenticated backend."""
from pathlib import Path
import subprocess
import unittest
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[2]


class VllmTest(unittest.TestCase):
    def test_candidate_override_is_pinned_and_keeps_hardware_settings(self):
        image = "registry.example/vllm-candidate@sha256:" + "1" * 64
        for mode in ("cpu", "gpu"):
            result = subprocess.run(["bash", str(ROOT / "scripts/vllm/install"),
                                     "--render", "--image", image, mode], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Image=" + image + "\n", result.stdout)
            self.assertEqual("AddDevice=nvidia.com/gpu=0" in result.stdout, mode == "gpu")
            self.assertIn('--default-chat-template-kwargs \'{"enable_thinking":true}\'', result.stdout)
            self.assertNotIn("PublishPort", result.stdout)
        for args in (("--image", "registry.example/vllm:latest", "cpu"),
                     ("--image",), ("cpu", "gpu")):
            result = subprocess.run(["bash", str(ROOT / "scripts/vllm/install"), "--render", *args],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("[Container]", result.stdout)

    def test_qwen_thinks_by_default_and_can_render_a_diagnostic_opt_out(self):
        template = Environment().from_string((ROOT / "configs/vllm/qwen3.jinja").read_text())
        args = {"messages": [{"role": "user", "content": "Say ready."}], "add_generation_prompt": True}
        for thinking in ({}, {"enable_thinking": True}):
            prompt = template.render(**args, **thinking)
            self.assertTrue(prompt.endswith("<|im_start|>assistant\n"), prompt)
        self.assertTrue(template.render(**args, enable_thinking=False).endswith("<think>\n\n</think>\n\n"))

    def test_rendered_services_keep_inference_private_and_pinned(self):
        for mode in ("cpu", "gpu"):
            result = subprocess.run(["bash", str(ROOT / "scripts/vllm/install"), "--render", mode],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            unit = result.stdout
            self.assertIn("Network=praxis.network", unit)
            self.assertIn("NetworkAlias=praxis-vllm", unit)
            self.assertNotIn("PublishPort", unit)
            self.assertIn("@sha256:", unit)
            self.assertIn("--revision b968826d9c46dd6066d109eabc6255188de91218", unit)
            self.assertIn("--served-model-name qwen3-8b", unit)
            self.assertNotIn("Secret=", unit)
            self.assertEqual("SecurityLabelDisable=true" in unit, mode == "gpu")
            self.assertEqual("AddDevice=nvidia.com/gpu=0" in unit, mode == "gpu")
            self.assertNotIn("Privileged=true", unit)
            self.assertIn('--default-chat-template-kwargs \'{"enable_thinking":true}\'', unit)


if __name__ == "__main__":
    unittest.main()
