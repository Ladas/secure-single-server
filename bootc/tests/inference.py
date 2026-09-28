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
        self.assertEqual(config['insecure_options'], {'allow_private_endpoints': True})
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
            result = subprocess.run(['python3', '-',
                                     str(ROOT / 'configs/vllm/harness/harness-provider.json.in'),
                                     str(output), '8080', 'Qwen/Qwen3-8B'],
                                    input=renderer, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            config = json.loads(output.read_text())
            self.assertEqual(config['model'], 'praxis/Qwen/Qwen3-8B')
            self.assertEqual(config['provider']['praxis']['models']['Qwen/Qwen3-8B']['limit'],
                             {'context': 16384, 'output': 2048})

    def test_reconciler_local_mode_does_not_consult_cloud_secrets(self):
        source = (ROOT / 'bootc/scripts/reconcile').read_text()
        block = source[source.index('backend="$(inference_backend)"'):
                       source.index('regex="$(selinux_path_regex')]
        for backend in ('vllm', 'cloud'):
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
            result = subprocess.run(['bash', '-c', script + block], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            if backend == 'vllm':
                self.assertNotIn('SECRET_CHECK', result.stdout)
                self.assertIn('/configs/vllm/praxis.yaml', result.stdout)
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
            for value, expected in [(None, 'cloud'), ('vllm', 'vllm'), ('cloud', 'cloud'),
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


if __name__ == '__main__':
    unittest.main()
