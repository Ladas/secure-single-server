#!/usr/bin/env python3
"""Validate generated profiles without downloading weights or requiring a GPU."""
import json
import shutil
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class VllmTests(unittest.TestCase):
    def render(self, mode, profile='any'):
        root = self.preflight_root(profile)
        return subprocess.run(
            ['bash', '-c', 'source "$1/scripts/common/lib.sh"; ROOT="$1"; '
             'source "$ROOT/bootc/scripts/vllm-lib"; vllm_render "$2"',
            'test', str(root), mode], text=True, capture_output=True)

    def preflight_root(self, profile):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for relative in ('scripts/common/lib.sh', 'bootc/scripts/vllm-lib',
                         'configs/vllm/images.env'):
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        (root / 'bootc/vllm-profile').write_text(profile + '\n')
        return root

    def test_shared_profiles_use_same_pinned_model_and_loopback_endpoint(self):
        for mode in ('cpu', 'gpu'):
            with self.subTest(mode=mode):
                result = self.render(mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                unit = result.stdout
                self.assertIn('Exec=Qwen/Qwen3-8B --revision b968826d9c46dd6066d109eabc6255188de91218', unit)
                self.assertIn('PublishPort=127.0.0.1:8000:8000', unit)
                self.assertNotIn('PublishPort=0.0.0.0:8000:8000', unit)
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

    def test_dedicated_vllm_profiles_publish_remote_endpoint(self):
        for mode in ('cpu', 'gpu'):
            with self.subTest(mode=mode):
                result = self.render(mode, profile=mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('PublishPort=0.0.0.0:8000:8000', result.stdout)
                self.assertNotIn('PublishPort=127.0.0.1:8000:8000', result.stdout)

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
        root = self.preflight_root('gpu')
        for topology in ('NVIDIA L4', 'NVIDIA L4\nNVIDIA L4', 'NVIDIA L40S', ''):
            result = subprocess.run(
                ['bash', '-c', 'source "$1/scripts/common/lib.sh"; ROOT="$1"; '
                 'source "$ROOT/bootc/scripts/vllm-lib"; '
                 'uname() { echo x86_64; }; nvidia-ctk() { :; }; '
                 'nvidia-smi() { printf "%s\\n" "$GPU_NAMES"; }; '
                 'GPU_NAMES="$2"; vllm_preflight gpu', 'test', str(root), topology],
                capture_output=True, text=True)
            self.assertEqual(result.returncode == 0, topology == 'NVIDIA L4', result.stderr)

    def test_preflight_rejects_image_profile_mismatch(self):
        root = self.preflight_root('gpu')
        result = subprocess.run(
            ['bash', '-c', 'source "$1/scripts/common/lib.sh"; ROOT="$1"; '
             'source "$ROOT/bootc/scripts/vllm-lib"; '
             'uname() { echo x86_64; }; vllm_preflight cpu',
             'test', str(root)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('this gpu vLLM image supports only gpu mode', result.stderr)


if __name__ == '__main__':
    unittest.main()
