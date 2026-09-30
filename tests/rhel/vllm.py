#!/usr/bin/env python3
"""Mutable RHEL inference must never publish its unauthenticated backend."""
from pathlib import Path
import subprocess
import unittest
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[2]


class VllmTest(unittest.TestCase):
    def test_quantized_model_selects_its_pinned_weights_and_native_template(self):
        for mode in ("cpu", "gpu"):
            result = subprocess.run(["bash", str(ROOT / "scripts/vllm/install"), "--render",
                                     "--model", "qwen3.8-27b-int4", mode], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            unit = result.stdout
            self.assertIn("Exec=RedHatAI/Qwen3.8-27B-INT4 ", unit)
            self.assertIn("--revision 91bd022d5b49442a868bc35008f6c21e1860edfa", unit)
            self.assertIn("--served-model-name qwen3.8-27b-int4", unit)
            self.assertIn("--tool-call-parser qwen3_xml", unit)
            self.assertIn("--reasoning-parser qwen3", unit)
            self.assertIn("--max-model-len 16384", unit)
            self.assertIn("--max-num-seqs 1", unit)
            self.assertIn('--default-chat-template-kwargs \'{"enable_thinking":true}\'', unit)
            self.assertNotIn("--chat-template ", unit)
            self.assertNotIn("chat-template.jinja", unit)
            self.assertNotIn("PublishPort", unit)

    def test_model_selection_rejects_unknown_and_duplicate_presets(self):
        for args in (("--model", "unknown", "cpu"), ("--model", "../qwen3-8b", "cpu"),
                     ("--model",), ("--model", "", "cpu"),
                     ("--model", "qwen3-8b", "--model", "qwen3.8-27b-int4", "cpu")):
            result = subprocess.run(["bash", str(ROOT / "scripts/vllm/install"), "--render", *args],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("[Container]", result.stdout)

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
