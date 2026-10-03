#!/usr/bin/env python3
"""Client contracts for the authenticated unified PriceTag gateway."""
import contextlib
import copy
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader('pricetag_harness', str(ROOT / 'scripts/pricetag/harness'))
spec = importlib.util.spec_from_loader(loader.name, loader)
client = importlib.util.module_from_spec(spec)
loader.exec_module(client)
sys.path.insert(0, str(ROOT / 'scripts/pricetag'))
import prepare
perf_loader = importlib.machinery.SourceFileLoader('pricetag_perf', str(ROOT / 'scripts/pricetag/perf'))
perf_spec = importlib.util.spec_from_loader(perf_loader.name, perf_loader)
perf = importlib.util.module_from_spec(perf_spec)
perf_loader.exec_module(perf)


class PreparationTest(unittest.TestCase):
    def test_mock_deployment_has_native_routes_and_no_provider_credentials(self):
        original, models = prepare.mock_inputs()
        rendered = prepare.render(original, models)
        self.assertEqual(models[0]['id'], 'demo-model')
        for chain in rendered['filter_chains']:
            for item in chain['filters']:
                if item['filter'] == 'credential_injection':
                    self.assertTrue(all(c.get('env_var') == 'M2M_SHARED_SECRET' for c in item['clusters']))
        self.assertNotIn('token_rate_limit', json.dumps(rendered))

    def test_vllm_only_excludes_cloud_routes_and_credentials_without_mutating_source(self):
        original = {'filter_chains': [{'name': api, 'filters': [
            {'filter': 'headers', 'request_remove': ['Authorization']},
            {'filter': 'credential_injection', 'clusters': [{'name': 'openai', 'env_var': 'OPENAI_API_KEY'}]},
            {'filter': 'load_balancer', 'clusters': [
                {'name': 'vllm', 'endpoints': ['vllm:8000']},
                {'name': 'openai', 'endpoints': ['api.openai.com:443']}]}]}
            for api in ('openai', 'anthropic')]}
        models = [{'id': 'local/model', 'provider': 'vllm'}, {'id': 'cloud/model', 'provider': 'openai'}]
        saved = copy.deepcopy(original)
        selected, catalog = prepare.vllm_only(original, models)
        self.assertEqual(original, saved)
        self.assertEqual(catalog, [models[0]])
        for chain in selected['filter_chains']:
            self.assertFalse(any(f['filter'] == 'credential_injection' for f in chain['filters']))
            clusters = next(f['clusters'] for f in chain['filters'] if f['filter'] == 'load_balancer')
            self.assertEqual([c['name'] for c in clusters], ['vllm'])

    def test_vllm_only_requires_a_local_model(self):
        with self.assertRaisesRegex(ValueError, 'vLLM'):
            prepare.vllm_only({'filter_chains': []}, [])


class PerformanceTest(unittest.TestCase):
    def test_stream_must_finish_and_report_expected_usage(self):
        usage = {'usage': {'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 5}}
        frame = b'data: ' + json.dumps(usage).encode() + b'\n\n'
        self.assertFalse(perf.valid_reply(frame, True))
        self.assertTrue(perf.valid_reply(frame + b'data: [DONE]\n\n', True))
        self.assertFalse(perf.valid_reply(b'data: [DONE]\n\n', True))
        self.assertTrue(perf.valid_reply(json.dumps(usage).encode(), False))

    def test_percentiles_use_nearest_rank_and_handle_empty_samples(self):
        self.assertEqual(perf.percentile([4, 2, 3, 1], .5), 2)
        self.assertEqual(perf.percentile([4, 2, 3, 1], .95), 4)
        self.assertIsNone(perf.percentile([], .95))


class HarnessTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.token = Path(self.directory.name) / 'caller.jwt'
        self.token.write_text('private.caller.signature')
        self.token.chmod(0o600)
        self.model = {'id': 'vllm/qwen3.8-27b-int4', 'praxis': {
            'provider': 'vllm', 'upstream_model': 'qwen3.8-27b-int4',
            'context': 32768, 'output': 8192, 'apis': ['openai', 'anthropic']}}

    def preview(self, name, *extra):
        output = io.StringIO()
        catalog = io.BytesIO(json.dumps({'data': [self.model]}).encode())
        with patch.object(sys, 'argv', ['harness', name, '--url', 'https://localhost:8443',
                '--token-file', str(self.token), '--model', self.model['id'], '--print-config', *extra]), \
             patch.object(client.urllib.request, 'build_opener') as opener, \
             patch.object(client.Path, 'home', return_value=Path(self.directory.name)), \
             contextlib.redirect_stdout(output):
            opener.return_value.open.return_value = catalog
            client.main()
        self.assertNotIn(self.token.read_text(), output.getvalue())
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://localhost:8443/v1/models')
        self.assertEqual(request.get_header('Authorization'), 'Bearer ' + self.token.read_text())
        return json.loads(output.getvalue())

    def test_unified_alias_uses_catalog_limits_for_every_harness(self):
        selected = self.preview('opencode')
        config = json.loads(selected['environment']['OPENCODE_CONFIG_CONTENT'])
        self.assertEqual(config['enabled_providers'], ['praxis'])
        self.assertEqual(config['disabled_providers'], [])
        provider = config['provider']['praxis']
        self.assertEqual(provider['options']['baseURL'], 'https://localhost:8443/v1')
        self.assertEqual(provider['models'][self.model['id']]['limit'], {'context': 32768, 'output': 8192})
        selected = self.preview('codex')
        self.assertIn('model_auto_compact_token_limit=24576', selected['command'])
        entry = next(Path(self.directory.name).rglob('codex-*.json'))
        self.assertEqual(json.loads(entry.read_text())['models'][0]['context_window'], 32768)
        selected = self.preview('claude-code')
        self.assertEqual(selected['environment']['ANTHROPIC_BASE_URL'], 'https://localhost:8443')
        self.assertEqual(selected['environment']['CLAUDE_CODE_MAX_OUTPUT_TOKENS'], '8192')
        self.assertEqual(selected['command'][-2:], ['--effort', 'medium'])

    def test_opencode_respects_anthropic_dialect_on_dual_api_model(self):
        selected = self.preview('opencode', '--api', 'anthropic')
        config = json.loads(selected['environment']['OPENCODE_CONFIG_CONTENT'])
        self.assertEqual(config['provider']['praxis']['npm'], '@ai-sdk/anthropic')

    def test_opencode_selects_anthropic_only_model_and_rejects_codex(self):
        self.model['praxis'].update(provider='external', apis=['anthropic'])
        selected = self.preview('opencode')
        config = json.loads(selected['environment']['OPENCODE_CONFIG_CONTENT'])
        self.assertEqual(config['provider']['praxis']['npm'], '@ai-sdk/anthropic')
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.preview('codex')

    def test_public_token_file_is_rejected_before_network(self):
        self.token.chmod(0o644)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.preview('opencode')

    def test_redirect_cannot_forward_caller_token(self):
        with self.assertRaisesRegex(ValueError, 'redirected'):
            client.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.test')


if __name__ == '__main__':
    unittest.main()
