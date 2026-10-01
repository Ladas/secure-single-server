#!/usr/bin/env python3
"""Regression checks for local routing and harness isolation configuration."""
import json
from pathlib import Path
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]


class InferenceTests(unittest.TestCase):
    def test_local_route_is_loopback_only_and_has_no_cloud_fallback(self):
        config = yaml.safe_load((ROOT / 'configs/vllm/praxis.yaml').read_text())
        self.assertEqual(config['insecure_options'], {'allow_private_endpoints': True,
                                                    'allow_private_upstreams': True})
        self.assertEqual(config['listeners'], [{'name': 'openai', 'address': '127.0.0.1:8080',
                                               'filter_chains': ['openai']}])
        self.assertEqual(config['admin']['address'], '127.0.0.1:9901')
        filters = config['filter_chains'][0]['filters']
        names = [f['filter'] for f in filters]
        self.assertNotIn('credential_injection', names)
        self.assertLess(names.index('token_rate_limit'), names.index('token_count'))
        upstream = next(f for f in filters if f['filter'] == 'load_balancer')
        self.assertEqual(upstream['clusters'], [{'name': 'openai', 'endpoints': ['127.0.0.1:8000'],
                                                'http': {'authority': 'localhost:8000'}}])
        headers = next(f for f in filters if f['filter'] == 'headers')
        self.assertIn('Authorization', headers['request_remove'])

    def test_remote_route_uses_one_private_upstream_and_keeps_praxis_loopback(self):
        rendered = (ROOT / 'configs/vllm/praxis-remote.yaml').read_text().replace(
            '@@VLLM_HOST@@', '10.0.1.10').replace('@@VLLM_PORT@@', '8000')
        config = yaml.safe_load(rendered)
        self.assertEqual(config['listeners'], [{'name': 'openai', 'address': '127.0.0.1:8080',
                                                'filter_chains': ['openai']}])
        self.assertEqual(config['admin']['address'], '127.0.0.1:9901')
        filters = config['filter_chains'][0]['filters']
        self.assertNotIn('credential_injection', [item['filter'] for item in filters])
        upstream = next(item for item in filters if item['filter'] == 'load_balancer')
        self.assertEqual(upstream['clusters'], [{'name': 'openai', 'endpoints': ['10.0.1.10:8000'],
                                                 'http': {'authority': '10.0.1.10:8000'}}])

    def test_admin_reports_remote_endpoint_and_requires_its_argument(self):
        source = (ROOT / 'bootc/scripts/admin').read_text()
        block = source[source.index('\n  inference)\n'):source.index('\n  status)\n')]
        block = block.replace('exec 9>/run/secure-single-server.lock', 'exec 9>/dev/null')
        script = """
set -euo pipefail
ROOT=/fixture
require_root() { :; }
validate_vllm_endpoint() { printf 'VALIDATE %s\\n' "$1"; }
inference_backend() { echo remote-vllm; }
inference_vllm_endpoint() { echo 10.0.1.10:8000; }
install() { printf 'INSTALL %s\\n' "$*"; }
 mktemp() { printf '/dev/null\\n'; }
chmod() { printf 'CHMOD %s\\n' "$*"; }
mv() { printf 'WRITE %s\\n' "$2"; }
flock() { :; }
systemctl() { printf 'SYSTEMCTL %s\\n' "$*"; }
die() { printf 'usage-error\\n' >&2; exit 1; }
admin() {
case "${1:-help}" in
""" + block + """  *) die 'unexpected command' ;;
esac
}
admin "$@"
"""
        result = subprocess.run(['bash', '-c', script, 'admin', 'inference', 'remote-vllm',
                                 '10.0.1.10:8000'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('WRITE /etc/secure-single-server/vllm-endpoint', result.stdout)
        self.assertIn('WRITE /etc/secure-single-server/inference-backend', result.stdout)

        result = subprocess.run(['bash', '-c', script, 'admin', 'inference', 'status'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Praxis upstream: remote-vllm', result.stdout)
        self.assertIn('Remote vLLM endpoint: 10.0.1.10:8000', result.stdout)

        result = subprocess.run(['bash', '-c', script, 'admin', 'inference'],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('usage-error', result.stderr)

    def test_inference_checks_survive_python_optimization(self):
        source = (ROOT / 'bootc/scripts/inference-check').read_text()
        self.assertNotIn('assert model ', source)
        self.assertNotIn('assert completion', source)
        self.assertIn("raise RuntimeError(f'{name}: expected model", source)
        self.assertIn("raise RuntimeError(f'{name}: empty completion", source)

    def test_local_quadlet_cannot_require_cloud_secrets_or_publish_public_ports(self):
        unit = (ROOT / 'configs/vllm/praxis.container.in').read_text()
        self.assertIn('Network=host', unit)
        self.assertNotIn('PublishPort=', unit)
        self.assertNotIn('Secret=', unit)
        self.assertIn('User=1001', unit)
        self.assertIn('Pull=never', unit)

    def test_harness_has_only_praxis_egress(self):
        policy = yaml.safe_load((ROOT / 'configs/vllm/harness/profiles/dev/policy.yaml')
                                .read_text().replace('@@PRAXIS_PORT@@', '8080'))
        self.assertEqual(list(policy['network_policies']), ['praxis_gateway'])
        self.assertEqual(policy['network_policies']['praxis_gateway']['endpoints'], [
            {'host': 'host.openshell.internal', 'port': 8080, 'protocol': 'rest',
             'access': 'read-write', 'enforcement': 'enforce'}])
        self.assertIn({'path': '/usr/local/bin/opencode'},
                      policy['network_policies']['praxis_gateway']['binaries'])
        config = json.loads((ROOT / 'configs/vllm/harness/harness-provider.json.in').read_text())
        self.assertEqual(config['provider']['praxis']['models']['@@MODEL_ID@@']['limit'],
                         {'context': 16384, 'output': 2048})
        self.assertEqual(list(config['provider']), ['praxis'])
        self.assertEqual(config['provider']['praxis']['options']['baseURL'],
                         'http://host.openshell.internal:@@PRAXIS_PORT@@/v1')

    def test_harness_renderer_preserves_local_token_limits(self):
        import tempfile
        source = (ROOT / 'openshell/harnesses/opencode/create.sh').read_text()
        renderer = source.split("<<'RENDER'\n", 1)[1].split('\nRENDER', 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'provider.json'
            # Bootc uses an empty API prefix; mutable RHEL Qwen uses /vllm.
            result = subprocess.run(['python3', '-',
                                     str(ROOT / 'configs/vllm/harness/harness-provider.json.in'),
                                     str(output), '8080', 'Qwen/Qwen3-8B', ''],
                                    input=renderer, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            config = json.loads(output.read_text())
            self.assertEqual(config['model'], 'praxis/Qwen/Qwen3-8B')
            self.assertEqual(config['provider']['praxis']['options']['baseURL'],
                             'http://host.openshell.internal:8080/v1')
            self.assertEqual(config['provider']['praxis']['models']['Qwen/Qwen3-8B']['limit'],
                             {'context': 16384, 'output': 2048})

    def test_reconciler_vllm_modes_do_not_consult_cloud_secrets(self):
        source = (ROOT / 'bootc/scripts/reconcile').read_text()
        block = source[source.index('backend="$(inference_backend)"'):
                       source.index('regex="$(selinux_path_regex')]
        for backend in ('vllm', 'remote-vllm', 'cloud'):
            script = """
set -euo pipefail
ROOT=/fixture; tmp=/fixture-tmp; DEFAULT_PRAXIS_IMAGE=pinned
inference_backend() { echo BACKEND_VALUE; }
service_uid() { echo 1001; }
service_gid() { echo 1001; }
install() { echo "INSTALL $*"; }
render_template() { echo "RENDER $*"; }
validate_secret_name() { :; }
secret_exists() { echo SECRET_CHECK; return 1; }
as_service() { echo "SERVICE $*"; }
note() { echo "$*"; }
die() { exit 1; }
""".replace("BACKEND_VALUE", backend)
            script = script.replace(f"inference_backend() {{ echo {backend}; }}",
                                    f"inference_backend() {{ echo {backend}; }}\n"
                                    "inference_vllm_endpoint() { echo 10.0.1.10:8000; }")
            result = subprocess.run(['bash', '-c', script + block], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            if backend == 'vllm':
                self.assertNotIn('SECRET_CHECK', result.stdout)
                self.assertIn('/configs/vllm/praxis.yaml', result.stdout)
                self.assertIn('/configs/vllm/praxis.container.in', result.stdout)
            elif backend == 'remote-vllm':
                self.assertNotIn('SECRET_CHECK', result.stdout)
                self.assertIn('/configs/vllm/praxis-remote.yaml', result.stdout)
                self.assertIn('VLLM_HOST 10.0.1.10 VLLM_PORT 8000', result.stdout)
                self.assertIn('/configs/vllm/praxis.container.in', result.stdout)
            else:
                self.assertIn('SECRET_CHECK', result.stdout)
                self.assertIn('stop praxis.service', result.stdout)
                self.assertNotIn('RENDER', result.stdout)

    def test_backend_selection_defaults_and_rejects_invalid_data(self):
        import tempfile
        # Exercise the real selector with an isolated state path; never source data.
        source = (ROOT / 'bootc/scripts/common').read_text().split('# Backend selection')[1]
        source = '# Backend selection' + source
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'backend'
            source = source.replace('/etc/secure-single-server/inference-backend', str(state))
            for value, expected in [(None, 'cloud'), ('vllm', 'vllm'),
                                    ('remote-vllm', 'remote-vllm'), ('cloud', 'cloud'),
                                    ('vllm\ncloud', None), ('$(touch BAD)', None)]:
                if value is not None:
                    state.write_text(value)
                result = subprocess.run(['bash', '-c', 'set -e; die() { exit 1; };\n' + source +
                                         '\ninference_backend'], capture_output=True, text=True)
                if expected is None:
                    self.assertNotEqual(result.returncode, 0)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), expected)

    def test_vllm_endpoint_validation_accepts_only_host_port(self):
        import shlex
        command = 'set -e; source ' + shlex.quote(str(ROOT / 'scripts/common/lib.sh')) + \
                  '; validate_vllm_endpoint "$1"'
        for endpoint in ('10.0.1.10:8000', '172.20.1.10:8000', '192.168.1.10:8000'):
            result = subprocess.run(['bash', '-c', command, 'validate', endpoint],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        for endpoint in ('http://10.0.1.10:8000', '10.0.1.10', '10.0.1.10:70000',
                         'bad..host:8000', 'bad/host:8000', 'vllm.internal:8000',
                         '8.8.8.8:8000', '172.32.1.10:8000', '10.0.1.256:8000',
                         '10.010.1.10:8000', '10.0.1.10:08000'):
            result = subprocess.run(['bash', '-c', command, 'validate', endpoint],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
