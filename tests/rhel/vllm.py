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
            self.assertIn("vLLM endpoint", result.stderr)

    def test_remote_removal_cleans_remote_state_without_touching_gateway_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            unit = root / "praxis-vllm.container"
            network_unit = root / "praxis.network"
            gateway_unit = root / "praxis.container"
            semanage_remove_marker = root / "semanage-remove"
            state.mkdir()
            unit.write_text("managed vLLM unit\n")
            network_unit.write_bytes((ROOT / "configs/common/quadlet/praxis.network").read_bytes())
            (state / "manifest").write_text("fixture-manifest\n")
            (state / "model").write_text("qwen3-8b\n")
            (state / "network-owned").write_text("")
            (state / "fcontext-owned").write_text("")

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
                    'vllm_uses_praxis_network() { return 0; }\n'
                    'sha256_file() { echo fixture-manifest; }\n'
                    'as_service() { printf \'AS_SERVICE %s\\n\' "$*"; }\n'
                    'note() { printf \'NOTE %s\\n\' "$*"; }\n'
                    'flock() { :; }\n'
                    'semanage() { if [[ "$1" == fcontext && "$2" == -d ]]; then touch ' +
                    shlex.quote(str(semanage_remove_marker)) + '; fi; }\n')
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
            self.assertFalse((state / "fcontext-owned").exists())
            self.assertFalse((state / "model").exists())
            self.assertIn('AS_SERVICE systemctl --user stop praxis-network.service', result.stdout)
            self.assertTrue(semanage_remove_marker.exists())

            unit.write_text("managed vLLM unit\n")
            network_unit.write_bytes((ROOT / "configs/common/quadlet/praxis.network").read_bytes())
            (state / "manifest").write_text("fixture-manifest\n")
            (state / "network-owned").write_text("")
            semanage_remove_marker.unlink()
            result = subprocess.run(['bash', str(removal_script(True))],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(unit.exists())
            self.assertTrue(network_unit.exists())
            self.assertTrue(gateway_unit.exists())
            self.assertFalse((state / "network-owned").exists())
            self.assertFalse(semanage_remove_marker.exists())
            self.assertNotIn('praxis-network.service', result.stdout)

            install_source = (ROOT / 'scripts/vllm/install').read_text()
            self.assertIn('install -d -o root -g "${gid}" -m 0750 "${quadlet_dir}"', install_source)
            self.assertIn('exec 9>"$(gateway_lock_path "${SERVICE_USER}")"', install_source)
            self.assertIn('ip -4 -o address show', install_source)
            self.assertIn('--remote address ${remote_listen} is not assigned to this server', install_source)

    def test_remote_install_rolls_back_staged_unit_and_network(self):
        source = (ROOT / 'scripts/vllm/install').read_text()
        cleanup = source[source.index('cleanup_install() {'):source.index('trap cleanup_install EXIT')]
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
            template = state / "chat-template.jinja"
            template_backup = state / "chat-template.jinja.previous"
            template_hash = state / "template.sha256"
            template_hash_backup = state / "template.sha256.previous"
            network_rm_marker = root / "network-rm"
            fcontext_rm_marker = root / "fcontext-rm"
            fcontext_owned = state / "fcontext-owned"
            state.mkdir()
            unit.write_text("new unit\n")
            network_unit.write_text("network\n")
            temporary.write_text("rendered\n")
            (state / "network-owned").write_text("")
            script = f"""
set -euo pipefail
state={shlex.quote(str(state))}
unit={shlex.quote(str(unit))}
unit_backup=''
network_unit={shlex.quote(str(network_unit))}
temporary={shlex.quote(str(temporary))}
manifest_new={shlex.quote(str(manifest_new))}
manifest_backup=''
fcontext_owned={shlex.quote(str(fcontext_owned))}
template_backup={shlex.quote(str(template_backup))}
template_hash_backup={shlex.quote(str(template_hash_backup))}
unit_staged=1
template_staged=0
network_staged=1
service_touched=0
service_was_active=0
fcontext_staged=0
fcontext_owned_staged=0
fcontext_regex='^/etc/praxis-vllm/chat-template\\.jinja$'
semanage() {{
  if [[ "$1" == fcontext && "$2" == -d ]]; then
    touch {shlex.quote(str(fcontext_rm_marker))}
  fi
}}
as_service() {{
  if [[ "$1" == podman && "$2" == network && "$3" == rm ]]; then
    touch {shlex.quote(str(network_rm_marker))}
  fi
  printf 'SERVICE %s\\n' "$*"
}}
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
            script = script.replace("network_staged=1", "network_staged=0")
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
            script = script.replace("unit_backup=''", f"unit_backup={shlex.quote(str(unit_backup))}")
            script = script.replace("manifest_backup=''", f"manifest_backup={shlex.quote(str(manifest_backup))}")
            script = script.replace("unit_staged=0", "unit_staged=1")
            script = script.replace("network_staged=0", "network_staged=1")
            result = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(unit.read_text(), "committed unit\n")
            self.assertEqual(manifest.read_text(), "committed manifest\n")
            self.assertFalse(manifest_new.exists())
            self.assertFalse(unit_backup.exists())
            self.assertFalse(manifest_backup.exists())
            self.assertFalse(network_unit.exists())

            template.write_text("new template\n")
            template_hash.write_text("new hash\n")
            template_backup.write_text("old template\n")
            template_hash_backup.write_text("old hash\n")
            script = script.replace("unit_staged=1", "unit_staged=0")
            script = script.replace("template_staged=0", "template_staged=1")
            script = script.replace("fcontext_staged=0", "fcontext_staged=1")
            script = script.replace("service_touched=0", "service_touched=1")
            script = script.replace("service_was_active=0", "service_was_active=1")
            result = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(template.read_text(), "old template\n")
            self.assertEqual(template_hash.read_text(), "old hash\n")
            self.assertFalse(template_backup.exists())
            self.assertFalse(template_hash_backup.exists())
            self.assertIn('SERVICE systemctl --user stop praxis-vllm.service', result.stdout)
            self.assertIn('SERVICE systemctl --user daemon-reload', result.stdout)
            self.assertIn('SERVICE systemctl --user restart praxis-vllm.service', result.stdout)
            self.assertIn('SERVICE systemctl --user stop praxis-network.service', result.stdout)
            self.assertTrue(network_rm_marker.exists())
            self.assertTrue(fcontext_rm_marker.exists())

            fcontext_rm_marker.unlink()
            fcontext_owned.write_text("")
            script = script.replace("template_staged=1", "template_staged=0")
            script = script.replace("fcontext_staged=1", "fcontext_staged=0")
            script = script.replace("fcontext_owned_staged=0", "fcontext_owned_staged=1")
            result = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(fcontext_owned.exists())
            self.assertFalse(fcontext_rm_marker.exists())

    def test_vllm_network_reference_detects_managed_unit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "etc/praxis-vllm"
            unit_directory = root / "etc/containers/systemd/users/1001"
            unit = unit_directory / "praxis-vllm.container"
            state.mkdir(parents=True)
            unit_directory.mkdir(parents=True)
            unit.write_text("Network=praxis.network\n")
            (state / "manifest").write_text("manifest\n")
            command = ('set -e; source ' + shlex.quote(str(ROOT / 'scripts/common/lib.sh')) +
                       '; vllm_uses_praxis_network "$1" 1001')
            result = subprocess.run(['bash', '-c', command, 'helper', str(root)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

            unit.write_text("Network=host\n")
            result = subprocess.run(['bash', '-c', command, 'helper', str(root)],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)

            unit.write_text("Network=praxis.network\n")
            (state / "manifest").unlink()
            result = subprocess.run(['bash', '-c', command, 'helper', str(root)],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)

    def test_gateway_uninstall_preserves_network_for_vllm(self):
        source = (ROOT / 'scripts/common/uninstall').read_text()
        block = source[source.index('network_unit='):source.index('as_service systemctl --user daemon-reload')]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            network_unit = root / 'praxis.network'
            other_file = root / 'other'
            manifest = root / 'manifest'
            block = block.replace(
                'network_unit="/etc/containers/systemd/users/$(service_uid)/praxis.network"',
                f'network_unit={shlex.quote(str(network_unit))}')

            def run_uninstall(preserve_network):
                network_unit.write_text('network\n')
                other_file.write_text('other\n')
                manifest.write_text(f'file {network_unit}\nfile {other_file}\n')
                script = f"""
set -euo pipefail
CONFIG_DIR={shlex.quote(str(root))}
MANIFEST_FILE={shlex.quote(str(manifest))}
validate_owned_path() {{ :; }}
selinux_path_regex() {{ echo fixture-regex; }}
semanage() {{ :; }}
as_service() {{ printf 'SERVICE %s\\n' "$*"; }}
vllm_uses_praxis_network() {{ return {0 if preserve_network else 1}; }}
{block}
"""
                return subprocess.run(['bash', '-c', script], capture_output=True, text=True)

            result = run_uninstall(True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(network_unit.exists())
            self.assertFalse(other_file.exists())
            self.assertNotIn('stop praxis-network.service', result.stdout)

            result = run_uninstall(False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(network_unit.exists())
            self.assertFalse(other_file.exists())
            self.assertIn('stop praxis-network.service', result.stdout)

    def test_remote_install_commits_state_and_clears_staging(self):
        source = (ROOT / 'scripts/vllm/install').read_text()
        commit = source[source.index('commit_install_state() {'):source.index('trap cleanup_install EXIT')]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"
            gateway_unit = root / "praxis.container"
            state.mkdir()
            (state / "network-owned").write_text("")
            commit = commit.replace(
                '/etc/containers/systemd/users/${uid}/praxis.container', str(gateway_unit))
            script = f"""
set -euo pipefail
state={shlex.quote(str(state))}
mode=gpu
model=test-model
remote_listen=10.0.1.10
uid=1001
unit_staged=1
template_staged=1
network_staged=1
service_touched=1
fcontext_staged=1
fcontext_owned_staged=1
{commit}
commit_install_state
printf '%s\\n' "$unit_staged" "$template_staged" "$fcontext_staged" "$fcontext_owned_staged" "$network_staged" "$service_touched"
"""
            result = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((state / "mode").read_text(), "gpu\n")
            self.assertEqual((state / "model").read_text(), "test-model\n")
            self.assertEqual((state / "listen-address").read_text(), "10.0.1.10\n")
            self.assertTrue((state / "network-owned").exists())
            self.assertEqual(result.stdout, "0\n0\n0\n0\n0\n0\n")

            gateway_unit.write_text("gateway\n")
            result = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((state / "network-owned").exists())

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
