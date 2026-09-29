#!/usr/bin/env python3
"""Mutable RHEL inference must never publish its unauthenticated backend."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class VllmTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
