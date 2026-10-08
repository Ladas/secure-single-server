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
user_loader = importlib.machinery.SourceFileLoader('pricetag_user', str(ROOT / 'scripts/pricetag/user'))
user_spec = importlib.util.spec_from_loader(user_loader.name, user_loader)
user = importlib.util.module_from_spec(user_spec)
user_loader.exec_module(user)
observe_loader = importlib.machinery.SourceFileLoader('pricetag_observe', str(ROOT / 'scripts/pricetag/observe'))
observe_spec = importlib.util.spec_from_loader(observe_loader.name, observe_loader)
observe = importlib.util.module_from_spec(observe_spec)
observe_loader.exec_module(observe)


class ObservationTest(unittest.TestCase):
    def test_failed_command_does_not_copy_arbitrary_output(self):
        with patch.object(observe.subprocess, 'run') as run:
            run.return_value.returncode = 1
            run.return_value.stdout = 'private-value'
            run.return_value.stderr = 'private-value'
            self.assertEqual(observe.command(['example']), {'error': 'command failed', 'exit_code': 1})

    def test_json_samples_preserve_numeric_metrics(self):
        with patch.object(observe.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = '{"database_bytes":123,"usage_events":4}'
            self.assertEqual(observe.command(['example'], True), {'database_bytes': 123, 'usage_events': 4})


class ProvisioningTest(unittest.TestCase):
    def provision(self, identities, expected_slug, exists=False, quota_error=False):
        calls = []

        def request(req, timeout):
            path = user.urllib.parse.urlsplit(req.full_url).path
            method = req.get_method()
            body = json.loads(req.data) if req.data and path != '/login' else None
            calls.append((method, path, body))
            result = {}
            if path == '/api/v1/admin/identities' and method == 'GET':
                result = identities
            elif path == '/api/v1/admin/people/' + expected_slug and not exists:
                error = user.urllib.error.HTTPError(req.full_url, 404, 'missing', {}, io.BytesIO())
                self.addCleanup(error.close)
                raise error
            elif path == '/api/v1/admin/people':
                result = {'slug': expected_slug}
            elif path == '/api/v1/admin/quota/overrides' and quota_error:
                error = user.urllib.error.HTTPError(req.full_url, 503, 'unavailable', {}, io.BytesIO())
                self.addCleanup(error.close)
                raise error
            return io.BytesIO(json.dumps(result).encode())

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(sys, 'argv', ['user', '--subject', 'alice', '--name', 'Alice',
                    '--rotate', '--monthly-usd', '5', '--output', str(Path(directory) / 'alice.jwt')]), \
                patch.object(user, 'private', return_value='test-credential'), \
                patch.object(user.ssl, 'create_default_context'), \
                patch.object(user.urllib.request, 'build_opener') as opener, \
                patch.object(user.subprocess, 'run') as issue, \
                patch.object(user.os, 'umask'), contextlib.redirect_stdout(io.StringIO()):
            opener.return_value.open.side_effect = request
            if quota_error:
                with self.assertRaises(user.urllib.error.HTTPError):
                    user.main()
                issue.assert_not_called()
            else:
                user.main()
                issue.assert_called_once()
                self.assertEqual(issue.call_args.args[0][1], 'rotate')
        self.assertEqual(calls[-1], ('PUT', '/api/v1/admin/quota/overrides',
            {'scope': 'user', 'principal': expected_slug, 'monthly_usd': 5}))
        return calls

    def test_empty_directory_creates_identity_before_budget_and_rotation(self):
        slug = 'jwt_' + user.hashlib.sha256(b'alice').hexdigest()[:24]
        for identities in (None, []):
            with self.subTest(identities=identities):
                calls = self.provision(identities, slug)
                self.assertEqual(calls[3:5], [
                    ('POST', '/api/v1/admin/people', {'slug': slug, 'full_name': 'Alice'}),
                    ('POST', '/api/v1/admin/identities', {'username': 'alice', 'person_slug': slug})])

    def test_retry_reuses_person_and_existing_identity(self):
        slug = 'jwt_' + user.hashlib.sha256(b'alice').hexdigest()[:24]
        calls = self.provision(None, slug, exists=True)
        self.assertFalse(any(path == '/api/v1/admin/people' for _, path, _ in calls))
        calls = self.provision([{'username': 'alice', 'person_slug': 'existing-person'}], 'existing-person')
        self.assertFalse(any(method == 'POST' and path != '/login' for method, path, _ in calls))

    def test_budget_failure_does_not_rotate_token(self):
        self.provision([{'username': 'alice', 'person_slug': 'existing-person'}],
                       'existing-person', quota_error=True)


class PreparationTest(unittest.TestCase):
    def test_price_seeds_precede_alias_copy_and_preserve_existing_rates(self):
        seeds = {'gpt-example': {'provider': 'openai', 'input': 1, 'output': 2,
                                'cache_read': 0, 'cache_write': 0}}
        sql = prepare.bootstrap([{'id': 'openai/gpt-example', 'model': 'gpt-example',
                                  'provider': 'openai'}], {}, 5, seeds)
        self.assertLess(sql.index('VALUES'), sql.index('DO $$'))
        self.assertIn('ON CONFLICT(model) DO NOTHING', sql)
        self.assertTrue(sql.startswith('BEGIN;'))
        self.assertTrue(sql.endswith('COMMIT;\n'))
        for bad in (-1, float('nan'), float('inf'), True, '1;DROP TABLE model_pricing'):
            seeds['gpt-example']['input'] = bad
            with self.assertRaises(ValueError):
                prepare.bootstrap([], {}, 5, seeds)

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
        self.catalog = [self.model]

    def preview(self, name, *extra):
        output = io.StringIO()
        catalog = io.BytesIO(json.dumps({'data': self.catalog}).encode())
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
        self.assertEqual(config['enabled_providers'], ['praxis-openai', 'praxis-messages'])
        self.assertEqual(config['disabled_providers'], [])
        self.assertEqual(config['small_model'], config['model'])
        provider = config['provider']['praxis-openai']
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
        self.assertEqual(config['provider']['praxis-messages']['npm'], '@ai-sdk/anthropic')
        self.assertEqual(config['model'], 'praxis-messages/' + self.model['id'])

    def test_opencode_selects_anthropic_only_model_and_rejects_codex(self):
        self.model['praxis'].update(provider='external', apis=['anthropic'])
        selected = self.preview('opencode')
        config = json.loads(selected['environment']['OPENCODE_CONFIG_CONTENT'])
        self.assertEqual(config['provider']['praxis-messages']['npm'], '@ai-sdk/anthropic')
        self.assertEqual(config['enabled_providers'], ['praxis-messages'])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.preview('codex')

    def test_opencode_lists_all_native_models_and_preserves_gateway_aliases(self):
        for alias, api, context, output in (
                ('openai/gpt-6-luna', 'openai', 1050000, 128000),
                ('pricetag/gpt-6-luna', 'openai', 400000, 32000),
                ('pricetag/claude-sonnet-5', 'anthropic', 128000, 8192)):
            self.catalog.append({'id': alias, 'praxis': {'provider': alias.split('/')[0],
                'upstream_model': alias.split('/', 1)[1], 'apis': [api],
                'context': context, 'output': output}})
        config = json.loads(self.preview('opencode')['environment']['OPENCODE_CONFIG_CONTENT'])
        providers = config['provider']
        for provider in providers.values():
            self.assertEqual(provider['whitelist'], list(provider['models']))
            self.assertEqual(provider['blacklist'], [])
        self.assertEqual(config['model'], 'praxis-openai/' + self.model['id'])
        self.assertEqual(set(providers['praxis-openai']['models']),
            {self.model['id'], 'openai/gpt-6-luna', 'pricetag/gpt-6-luna'})
        self.assertEqual(set(providers['praxis-messages']['models']),
            {self.model['id'], 'pricetag/claude-sonnet-5'})
        for item in self.catalog[1:]:
            provider = providers['praxis-openai' if item['praxis']['apis'] == ['openai'] else 'praxis-messages']
            model = provider['models'][item['id']]
            self.assertEqual(model['limit'], {k: item['praxis'][k] for k in ('context', 'output')})
            self.assertEqual(provider['options']['baseURL'], 'https://localhost:8443/v1')
            if item['praxis']['apis'] == ['openai']:
                self.assertEqual(model['provider']['npm'], '@ai-sdk/openai')

    def test_opencode_rejects_invalid_limits_in_unselected_model(self):
        invalid = copy.deepcopy(self.model)
        invalid['id'] = 'other/model'
        invalid['praxis']['output'] = invalid['praxis']['context']
        self.catalog.append(invalid)
        with self.assertRaisesRegex(ValueError, 'limits'):
            self.preview('opencode')

    def test_opencode_glm_is_text_only_with_hosted_limits(self):
        self.model.update(id='pricetag/rits/zai-org/glm-5-3', praxis={
            'provider': 'pricetag', 'upstream_model': 'rits/zai-org/glm-5-3',
            'context': 262144, 'output': 65536, 'apis': ['anthropic']})
        config = json.loads(self.preview('opencode')['environment']['OPENCODE_CONFIG_CONTENT'])
        entry = config['provider']['praxis-messages']['models'][self.model['id']]
        self.assertEqual(entry['limit'], {'context': 262144, 'output': 65536})
        self.assertEqual(entry['modalities'], {'input': ['text'], 'output': ['text']})
        self.assertFalse(entry['attachment'])

    def test_public_token_file_is_rejected_before_network(self):
        self.token.chmod(0o644)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.preview('opencode')

    def test_redirect_cannot_forward_caller_token(self):
        with self.assertRaisesRegex(ValueError, 'redirected'):
            client.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.test')


if __name__ == '__main__':
    unittest.main()
