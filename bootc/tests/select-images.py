#!/usr/bin/env python3

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "bootc/ci/select-images.py"


class SelectImagesTests(unittest.TestCase):
    def select(self, paths):
        result = subprocess.run(
            ["python3", str(SCRIPT)],
            input="\n".join(paths) + "\n",
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(result.stdout)

    def test_base_change_selects_harnesses(self):
        selected = self.select(["bootc/scripts/common"])
        self.assertEqual(selected, {
            "praxis": False,
            "vllm_cpu": False,
            "vllm_gpu": False,
            "harnesses": True,
        })

    def test_praxis_only_change_selects_praxis(self):
        selected = self.select(["bootc/Containerfile.praxis"])
        self.assertEqual(selected, {
            "praxis": True,
            "vllm_cpu": False,
            "vllm_gpu": False,
            "harnesses": False,
        })

    def test_vllm_cpu_only_change_selects_cpu(self):
        selected = self.select(["bootc/Containerfile.vllm.cpu"])
        self.assertEqual(selected, {
            "praxis": False,
            "vllm_cpu": True,
            "vllm_gpu": False,
            "harnesses": False,
        })

    def test_vllm_gpu_only_change_selects_gpu(self):
        selected = self.select(["bootc/install-nvidia"])
        self.assertEqual(selected, {
            "praxis": False,
            "vllm_cpu": False,
            "vllm_gpu": True,
            "harnesses": False,
        })

    def test_shared_vllm_change_selects_both_profiles(self):
        selected = self.select(["bootc/scripts/vllm-common"])
        self.assertEqual(selected, {
            "praxis": False,
            "vllm_cpu": True,
            "vllm_gpu": True,
            "harnesses": True,
        })

    def test_harness_only_change_selects_harnesses(self):
        selected = self.select(["openshell/harnesses/opencode/create.sh"])
        self.assertEqual(selected, {
            "praxis": False,
            "vllm_cpu": False,
            "vllm_gpu": False,
            "harnesses": True,
        })

    def test_ci_change_selects_all_image_groups(self):
        selected = self.select([".github/workflows/bootc-images.yml"])
        self.assertEqual(selected, {
            "praxis": True,
            "vllm_cpu": True,
            "vllm_gpu": True,
            "harnesses": True,
        })

    def test_ignored_path_selects_nothing(self):
        selected = self.select(["README.md"])
        self.assertEqual(selected, {
            "praxis": False,
            "vllm_cpu": False,
            "vllm_gpu": False,
            "harnesses": False,
        })


if __name__ == "__main__":
    unittest.main()
