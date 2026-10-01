#!/usr/bin/env python3
"""Mutable RHEL inference must expose only an explicitly selected private address."""
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/common"))
from harness import configuration


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
            self.assertIn("--max-model-len 32768", unit)
            self.assertIn("--max-num-seqs 1", unit)
            self.assertIn('--default-chat-template-kwargs \'{"enable_thinking":true}\'', unit)
            self.assertNotIn("--chat-template ", unit)
            self.assertNotIn("chat-template.jinja", unit)
            self.assertNotIn("PublishPort", unit)

    def test_server_and_client_context_limits_match_for_each_preset(self):
        for model, context in (("qwen3-8b", 16384), ("qwen3.8-27b-int4", 32768)):
            for mode in ("cpu", "gpu"):
                with self.subTest(model=model, mode=mode):
                    result = subprocess.run(["bash", str(ROOT / "scripts/vllm/install"), "--render",
                                             "--model", model, mode], capture_output=True, text=True, check=True)
                    command, _ = configuration("codex", "vllm", model, "http://127.0.0.1:8080", "caller")
                    self.assertIn(f"--max-model-len {context} ", result.stdout)
                    self.assertIn(f"model_context_window={context}", command)

    def test_remote_mode_publishes_only_the_requested_private_address(self):
        result = subprocess.run(["bash", str(ROOT / "scripts/vllm/install"), "--render",
                                 "--remote", "10.0.1.10", "gpu"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PublishPort=10.0.1.10:8000:8000\n", result.stdout)
        self.assertIn("Network=praxis.network", result.stdout)
        self.assertIn("AddDevice=nvidia.com/gpu=0", result.stdout)
        result = subprocess.run(["bash", str(ROOT / "scripts/vllm/install"), "--render",
                                 "--remote", "", "cpu"], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--remote requires one private IPv4 address", result.stderr)
        for address in ("8.8.8.8", "203.0.113.1", "10.0.1.256", "localhost"):
            result = subprocess.run(["bash", str(ROOT / "scripts/vllm/install"), "--render",
                                     "--remote", address, "cpu"],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("[Container]", result.stdout)
            self.assertIn("--remote requires an RFC1918 IPv4 address", result.stderr)

    def test_remote_removal_cleans_remote_state_without_touching_gateway_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            unit = root / "praxis-vllm.container"
            network_unit = root / "praxis.network"
            gateway_unit = root / "praxis.container"
            state.mkdir()
            unit.write_text("managed vLLM unit\n")
            network_unit.write_bytes((ROOT / "configs/common/quadlet/praxis.network").read_bytes())
            (state / "manifest").write_text("fixture-manifest\n")
            (state / "model").write_text("qwen3-8b\n")
            (state / "network-owned").write_text("")

            def removal_script(with_gateway):
                if with_gateway:
                    gateway_unit.write_text("managed gateway unit\n")
                else:
                    gateway_unit.unlink(missing_ok=True)
                source = (ROOT / "scripts/vllm/remove").read_text()
                source = source.replace(
                    'ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"',
                    f'ROOT={shlex.quote(str(ROOT))}')
                source = source.replace(
                    'source "${ROOT}/scripts/common/lib.sh"',
                    'require_root() { :; }\n'
                    'die() { printf \'error: %s\\n\' "$*" >&2; exit 1; }\n'
                    'service_uid() { echo 1001; }\n'
                    'sha256_file() { echo fixture-manifest; }\n'
                    'as_service() { printf \'AS_SERVICE %s\\n\' "$*"; }\n'
                    'note() { printf \'NOTE %s\\n\' "$*"; }\n'
                    'flock() { :; }\n'
                    'semanage() { :; }\n')
                source = source.replace('/run/lock/praxis-vllm.lock', str(root / "vllm.lock"))
                source = source.replace('$(gateway_lock_path "${SERVICE_USER}")', str(root / "gateway.lock"))
                source = source.replace('state=/etc/praxis-vllm', f'state={state}')
                source = source.replace(
                    'unit="/etc/containers/systemd/users/$(service_uid)/praxis-vllm.container"',
                    f'unit={unit}')
                source = source.replace(
                    'network_unit="/etc/containers/systemd/users/$(service_uid)/praxis.network"',
                    f'network_unit={network_unit}')
                source = source.replace(
                    'gateway_unit="/etc/containers/systemd/users/$(service_uid)/praxis.container"',
                    f'gateway_unit={gateway_unit}')
                script = root / ("remove-with-gateway.sh" if with_gateway else "remove-standalone.sh")
                script.write_text(source)
                return script

            result = subprocess.run(['bash', str(removal_script(False))],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(unit.exists())
            self.assertFalse(network_unit.exists())
            self.assertFalse((state / "network-owned").exists())
            self.assertFalse((state / "model").exists())
            self.assertIn('AS_SERVICE systemctl --user stop praxis-network.service', result.stdout)

            unit.write_text("managed vLLM unit\n")
            network_unit.write_bytes((ROOT / "configs/common/quadlet/praxis.network").read_bytes())
            (state / "manifest").write_text("fixture-manifest\n")
            (state / "network-owned").write_text("")
            result = subprocess.run(['bash', str(removal_script(True))],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(unit.exists())
            self.assertTrue(network_unit.exists())
            self.assertTrue(gateway_unit.exists())
            self.assertFalse((state / "network-owned").exists())
            self.assertNotIn('praxis-network.service', result.stdout)

            install_source = (ROOT / 'scripts/vllm/install').read_text()
            self.assertIn('install -d -o root -g "${gid}" -m 0750 "${quadlet_dir}"', install_source)
            self.assertIn('exec 9>"$(gateway_lock_path "${SERVICE_USER}")"', install_source)
            self.assertIn('ip -4 -o address show', install_source)
            self.assertIn('--remote address ${remote_listen} is not assigned to this server', install_source)

    def test_remote_install_rolls_back_staged_unit_and_network(self):
        source = (ROOT / 'scripts/vllm/install').read_text()
        cleanup = source[source.index('cleanup_install() {'):source.index('trap cleanup_install EXIT')]
        install_block = source[
            source.index('unit_staged=1'):
            source.index('as_service systemctl --user daemon-reload')]
        success_block = source[
            source.index('as_service systemctl --user daemon-reload'):
            source.index("die 'vLLM did not become ready")]
        self.assertNotIn('unit_staged=0', install_block)
        self.assertNotIn('network_staged=0', install_block)
        self.assertIn('unit_staged=0', success_block)
        self.assertIn('network_staged=0', success_block)
        self.assertLess(success_block.index('unit_staged=0'), success_block.index('exit 0'))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            unit = root / "praxis-vllm.container"
            unit_backup = root / "praxis-vllm.container.previous"
            network_unit = root / "praxis.network"
            temporary = root / "rendered"
            manifest = state / "manifest"
            manifest_backup = state / "manifest.previous"
            manifest_new = state / "manifest.new"
            state.mkdir()
            unit.write_text("new unit\n")
            network_unit.write_text("network\n")
            temporary.write_text("rendered\n")
            (state / "network-owned").write_text("")
            script = f"""
set -euo pipefail
state={shlex.quote(str(state))}
unit={shlex.quote(str(unit))}
unit_backup={shlex.quote(str(unit_backup))}
network_unit={shlex.quote(str(network_unit))}
temporary={shlex.quote(str(temporary))}
manifest_new={shlex.quote(str(manifest_new))}
manifest_backup={shlex.quote(str(manifest_backup))}
unit_staged=1
network_staged=1
{cleanup}
cleanup_install
"""
            result = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(unit.exists())
            self.assertFalse(manifest.exists())
            self.assertFalse(network_unit.exists())
            self.assertFalse((state / "network-owned").exists())
            self.assertFalse(temporary.exists())

            network_unit.write_text("network\n")
            unit.write_text("committed unit\n")
            temporary.write_text("rendered\n")
            (state / "network-owned").write_text("")
            manifest.write_text("committed\n")
            script = script.replace("unit_staged=1", "unit_staged=0")
            result = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(network_unit.exists())
            self.assertTrue(unit.exists())
            self.assertTrue(manifest.exists())
            self.assertTrue((state / "network-owned").exists())
            self.assertFalse(temporary.exists())

            unit.write_text("replacement unit\n")
            manifest.write_text("replacement manifest\n")
            unit_backup.write_text("committed unit\n")
            manifest_backup.write_text("committed manifest\n")
            manifest_new.write_text("replacement manifest\n")
            script = script.replace("unit_staged=0", "unit_staged=1")
            result = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(unit.read_text(), "committed unit\n")
            self.assertEqual(manifest.read_text(), "committed manifest\n")
            self.assertFalse(manifest_new.exists())
            self.assertFalse(unit_backup.exists())
            self.assertFalse(manifest_backup.exists())

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
