#!/usr/bin/env python3
"""Validate generated profiles without downloading weights or requiring a GPU."""
import json
import shlex
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class VllmTests(unittest.TestCase):
    def render(self, mode):
        return subprocess.run(
            ['bash', '-c', 'source "$1/scripts/common/lib.sh"; ROOT="$1"; '
             'source "$ROOT/bootc/scripts/vllm-lib"; vllm_render "$2"',
             'test', str(ROOT), mode], text=True, capture_output=True)

    def test_both_profiles_use_same_pinned_model_and_private_endpoint(self):
        for mode in ('cpu', 'gpu'):
            with self.subTest(mode=mode):
                result = self.render(mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                unit = result.stdout
                self.assertIn('Exec=Qwen/Qwen3-8B --revision b968826d9c46dd6066d109eabc6255188de91218', unit)
                self.assertIn('PublishPort=127.0.0.1:8000:8000', unit)
                arguments = shlex.split(next(line[5:] for line in unit.splitlines()
                                             if line.startswith('Exec=')))
                provider = json.loads((ROOT / 'configs/vllm/harness/harness-provider.json.in').read_text())
                context = provider['provider']['praxis']['models']['@@MODEL_ID@@']['limit']['context']
                self.assertEqual(int(arguments[arguments.index('--max-model-len') + 1]), context)
                self.assertEqual(json.loads(arguments[arguments.index('--default-chat-template-kwargs') + 1]),
                                 {'enable_thinking': False})
                self.assertIn('Pull=never', unit)
                self.assertIn('User=1001', unit)
                self.assertIn('Volume=%h/cache:/cache:Z', unit)
                self.assertNotIn('Network=host', unit)
                self.assertNotIn('ipc=host', unit)
                self.assertNotIn('[Install]', unit)  # Boot reconciler must pull before start.

    def test_cpu_does_not_request_gpu_devices_or_disable_selinux(self):
        unit = self.render('cpu').stdout
        self.assertIn('vllm-openai-cpu@sha256:', unit)
        self.assertIn('VLLM_CPU_KVCACHE_SPACE=4', unit)
        self.assertNotIn('AddDevice=', unit)
        self.assertNotIn('SecurityLabelDisable=', unit)
        self.assertNotIn('--gpu-memory-utilization', unit)

    def test_gpu_selects_one_device(self):
        unit = self.render('gpu').stdout
        self.assertIn('vllm/vllm-openai@sha256:', unit)
        self.assertIn('AddDevice=nvidia.com/gpu=0', unit)
        self.assertIn('--tensor-parallel-size 1', unit)

    def test_unknown_mode_cannot_generate_unit(self):
        for mode in ('disabled', 'auto', 'cpu\nAddDevice=/dev/mem'):
            result = self.render(mode)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')

    def test_gpu_preflight_rejects_unsupported_topology(self):
        for topology in ('NVIDIA L4', 'NVIDIA L4\nNVIDIA L4', 'NVIDIA L40S', ''):
            result = subprocess.run(
                ['bash', '-c', 'source "$1/scripts/common/lib.sh"; ROOT="$1"; '
                 'source "$ROOT/bootc/scripts/vllm-lib"; '
                 'uname() { echo x86_64; }; nvidia-ctk() { :; }; '
                 'nvidia-smi() { printf "%s\\n" "$GPU_NAMES"; }; '
                 'GPU_NAMES="$2"; vllm_preflight gpu', 'test', str(ROOT), topology],
                capture_output=True, text=True)
            self.assertEqual(result.returncode == 0, topology == 'NVIDIA L4', result.stderr)


if __name__ == '__main__':
    unittest.main()
