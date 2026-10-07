"""Offline provider discovery, private-secret and export contracts."""
import contextlib
import importlib.util
import importlib.machinery
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader('setup', str(ROOT / 'scripts/pricetag/providers'))
spec = importlib.util.spec_from_loader(loader.name, loader)
setup = importlib.util.module_from_spec(spec)
loader.exec_module(setup)
sys.path.insert(0, str(ROOT / 'scripts/common'))
sys.path.insert(0, str(ROOT / 'scripts/pricetag'))
from gateway import render as gateway


class SetupTest(unittest.TestCase):
    def test_pricetag_prompts_once_and_derives_documented_endpoint_pair(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(setup, 'STATE', Path(directory)), \
                patch.object(setup.sys.stdin, 'isatty', return_value=True), \
                patch('builtins.input', return_value='ai-gateway-unified-test.example/v1/') as prompts, \
                patch.object(setup.getpass, 'getpass', return_value='SECRET'), \
                patch.object(setup, 'provider_settings', side_effect=ValueError('test stop')) as settings, \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'test stop'):
                setup.add_provider('pricetag')
        self.assertEqual(prompts.call_count, 1)
        self.assertEqual(settings.call_args.kwargs['urls'],
                         {'anthropic': 'https://ai-gateway-unified-test.example',
                          'openai': 'https://ai-gateway-openai-test.example/v1'})

    def test_one_base_supports_shared_host_and_openai_host_input(self):
        self.assertEqual(setup.pricetag_urls('example.com/v1/'),
                         {'anthropic': 'https://example.com', 'openai': 'https://example.com/v1'})
        self.assertEqual(setup.pricetag_urls('ai-gateway-openai-test.example:8443'),
                         {'anthropic': 'https://ai-gateway-unified-test.example:8443',
                          'openai': 'https://ai-gateway-openai-test.example:8443/v1'})

    def test_debug_reports_http_failure_without_key_or_response_body(self):
        def reject(request, timeout):
            raise setup.urllib.error.HTTPError(request.full_url, 401, 'SECRET',
                {'x-request-id': 'SECRET', 'Content-Type': 'application/json'}, io.BytesIO(b'SECRET BODY'))
        with patch.object(setup, 'DEBUG', True), \
                patch.object(setup.urllib.request, 'build_opener', return_value=SimpleNamespace(open=reject)), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(ValueError):
                setup.discover_models('https://example.com/v1', 'openai', 'SECRET')
        self.assertIn('401', out.getvalue())
        self.assertIn('Authorization: Bearer', out.getvalue())
        self.assertNotIn('SECRET', out.getvalue())
        self.assertNotIn('BODY', out.getvalue())

    def test_export_requires_a_provider(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(setup, 'STATE', Path(directory)):
            with self.assertRaisesRegex(ValueError, 'at least one provider'):
                setup.export()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_export_supports_each_provider_independently(self):
        for name in ('openai', 'pricetag'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                state = Path(directory)
                alias = name + '/gpt-5.4-mini'
                record = {'models': [{'id': alias, 'provider': name, 'model': 'gpt-5.4-mini',
                    'apis': ['openai'], 'context': 400000, 'output': 128000}],
                    'prices': {alias: 'gpt-5.4-mini'}, 'urls': {'openai': 'https://example.com/v1'},
                    'secret': 'praxis-' + name + '-api-key-v1'}
                (state / ('provider-' + name + '.json')).write_text(json.dumps(record))
                with patch.object(setup, 'STATE', state), \
                        patch.object(setup, 'service', return_value=SimpleNamespace(returncode=0)), \
                        contextlib.redirect_stdout(io.StringIO()):
                    setup.export()
                config = gateway(json.loads((state / 'providers.json').read_text()), record['models'])
                self.assertIn(alias, json.dumps(config))
                unit = (state / 'provider-secrets.container').read_text()
                self.assertEqual(unit.count('Secret='), 1)
                self.assertIn('target=' + ('OPENAI_API_KEY' if name == 'openai' else 'CUSTOM_PRICETAG_API_KEY'), unit)

    def test_replace_failure_retains_previous_provider_record(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            previous = state / 'provider-openai.json'
            previous.write_text('{"secret":"old-reference"}')
            with patch.object(setup, 'STATE', state), \
                    patch.object(setup.sys.stdin, 'isatty', return_value=True), \
                    patch.object(setup.getpass, 'getpass', return_value='SECRET_SENTINEL'), \
                    patch.object(setup, 'provider_settings', side_effect=ValueError('HTTP 401')), \
                    patch.object(setup, 'service') as service, contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError, 'HTTP 401'):
                    setup.add_provider('openai', replace=True)
            service.assert_not_called()
            self.assertEqual(previous.read_text(), '{"secret":"old-reference"}')

    def test_provider_url_normalization(self):
        for value in ('example.com', 'example.com/v1/', 'https://example.com/', 'https://example.com/v1'):
            self.assertEqual(setup.normalize_url(value, 'openai'), 'https://example.com/v1')
            self.assertEqual(setup.normalize_url(value, 'anthropic'), 'https://example.com')
        for value in ('http://example.com', 'https://user:pass@example.com', 'example.com/other', 'example.com?key=x'):
            with self.assertRaises(ValueError):
                setup.normalize_url(value, 'openai')

    def test_missing_messages_preset_does_not_discard_working_openai_models(self):
        with patch.object(setup, 'discover_models', side_effect=[[], [{'id': 'gpt-6-luna'}]]), \
                patch.object(setup, 'service', return_value=SimpleNamespace(returncode=1)), \
                contextlib.redirect_stdout(io.StringIO()):
            settings = setup.provider_settings('pricetag', 'both', 'https://example.com', 'SECRET',
                urls={'anthropic': 'https://example.com', 'openai': 'https://example.com/v1'})
        self.assertEqual(settings['models'][0]['model'], 'gpt-6-luna')
        self.assertEqual(set(settings['urls']), {'openai'})

    def test_fixed_providers_render_both_apis_without_saving_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            secrets = set()
            def service(*args, **kwargs):
                self.assertNotIn('SECRET_SENTINEL', str(args))
                if args[1:3] == ('secret', 'exists'):
                    return SimpleNamespace(returncode=0 if args[3] in secrets else 1)
                if args[1:3] == ('secret', 'create'):
                    self.assertEqual(kwargs['input'], b'SECRET_SENTINEL')
                    secrets.add(args[3])
                    return SimpleNamespace(returncode=0)
                return SimpleNamespace(stdout=json.dumps([{'Os': 'linux', 'Architecture': 'amd64', 'Id': 'a' * 64}]))
            def discover(url, api, key):
                self.assertEqual(key, 'SECRET_SENTINEL')
                return [{'id': m[0]} for m in setup.PRESETS[api]]
            with patch.object(setup, 'ROOT', ROOT), patch.object(setup, 'STATE', state), \
                    patch.object(setup, 'DEPLOY', state), \
                    patch.object(setup, 'service', side_effect=service), \
                    patch.object(setup, 'discover_models', side_effect=discover), \
                    patch.object(setup.sys.stdin, 'isatty', return_value=True), \
                    patch.object(setup.getpass, 'getpass', return_value='SECRET_SENTINEL'), \
                    patch('builtins.input', side_effect=['https://messages.example', 'https://chat.example/v1/']), \
                    patch.object(setup.subprocess, 'run') as run, contextlib.redirect_stdout(io.StringIO()) as out:
                setup.add_provider('openai')
                setup.add_provider('pricetag', urls={'anthropic': 'messages.example', 'openai': 'chat.example/v1/'})
                setup.export()
                run.assert_not_called()
            self.assertNotIn('SECRET_SENTINEL', out.getvalue())
            for path in state.iterdir():
                self.assertNotIn('SECRET_SENTINEL', path.read_text())
            models = json.loads((state / 'models.json').read_text())
            self.assertEqual(len(models), 9)
            config = gateway(json.loads((state / 'providers.json').read_text()), models)
            serialized = json.dumps(config)
            for expected in ('messages.example', 'chat.example', '/v1/messages', '/v1/responses'):
                self.assertIn(expected, serialized)
            self.assertNotIn('/v1/v1', serialized)
            self.assertNotIn('token_rate_limit', serialized)
            def objects(value):
                if isinstance(value, dict):
                    yield value
                    for child in value.values():
                        yield from objects(child)
                elif isinstance(value, list):
                    for child in value:
                        yield from objects(child)
            nodes = list(objects(config))
            for alias, cluster, path in (
                    ('openai/gpt-6-luna', 'openai', '/v1/responses'),
                    ('pricetag/gpt-6-luna', 'pricetag-openai', '/v1/responses'),
                    ('pricetag/claude-sonnet-5', 'pricetag-anthropic', '/v1/messages')):
                self.assertIn({'path': path, 'headers': {'X-Gateway-Model': alias},
                               'cluster': cluster}, nodes)
                self.assertTrue(any(
                    node.get('request_replace') == [{'pointer': '/model', 'value': alias.split('/', 1)[1]}]
                    and node.get('conditions') == [{'when': {'methods': ['POST'],
                        'headers': {'X-Gateway-Model': alias}}}] for node in nodes))

    def test_fixed_models_require_no_model_or_limit_prompts(self):
        catalog = [{'id': 'gpt-5.4-mini'}, {'id': 'gpt-6-luna'}, {'id': 'gpt-6.1-sol'}]
        with patch.object(setup, 'discover_models', return_value=catalog), \
                patch.object(setup, 'service', return_value=SimpleNamespace(returncode=1)), \
                patch('builtins.input', side_effect=AssertionError('No wizard prompts')), \
                contextlib.redirect_stdout(io.StringIO()):
            settings = setup.provider_settings('openai', 'openai', 'https://api.openai.com', 'SECRET')
        self.assertEqual(len(settings['models']), 3)
        self.assertEqual([m['context'] for m in settings['models']], [400000, 1050000, 1050000])
        self.assertTrue(all(m['output'] == 128000 for m in settings['models']))
        self.assertEqual(settings['prices']['openai/gpt-6.1-sol'], 'gpt-6.1-sol')

    def test_unavailable_presets_are_skipped_and_lower_advertised_limits_respected(self):
        catalog = [{'id': 'gpt-6-luna', 'praxis': {'context': 262144, 'output': 32768}}]
        with patch.object(setup, 'discover_models', return_value=catalog), \
                patch.object(setup, 'service', return_value=SimpleNamespace(returncode=1)), \
                contextlib.redirect_stdout(io.StringIO()):
            settings = setup.provider_settings('pricetag', 'openai', 'https://remote.example', 'SECRET')
        self.assertEqual(len(settings['models']), 1)
        self.assertEqual(settings['models'][0]['context'], 262144)
        self.assertEqual(settings['models'][0]['output'], 32768)
        with patch.object(setup, 'discover_models', return_value=[{'id': 'unknown'}]):
            with self.assertRaisesRegex(ValueError, 'No preset models'):
                setup.provider_settings('openai', 'openai', 'https://api.openai.com', 'SECRET')

    def test_discovery_uses_native_auth_and_does_not_echo_provider_errors(self):
        for api, header, value in [('openai', 'Authorization', 'Bearer SECRET'),
                                    ('anthropic', 'X-api-key', 'SECRET')]:
            response = json.dumps({'data': [{'id': 'model-a', 'praxis': {
                'context': 32768, 'output': 4096}}, {'id': '\u001b[31mBAD'}]}).encode()
            opener = SimpleNamespace(open=lambda request, timeout: io.BytesIO(response))
            with patch.object(setup.urllib.request, 'build_opener', return_value=opener):
                models = setup.discover_models('https://remote.example/v1', api, 'SECRET')
            self.assertEqual([m['id'] for m in models], ['model-a'])
            def reject(request, timeout):
                self.assertEqual(request.get_header(header), value)
                self.assertEqual(request.full_url, 'https://remote.example/v1/models')
                raise setup.urllib.error.HTTPError(request.full_url, 401, 'SECRET', {}, None)
            with patch.object(setup.urllib.request, 'build_opener',
                              return_value=SimpleNamespace(open=reject)):
                with self.assertRaisesRegex(ValueError, 'HTTP 401') as error:
                    setup.discover_models('https://remote.example', api, 'SECRET')
                self.assertNotIn('SECRET', str(error.exception))

    def test_redirects_and_insecure_provider_urls_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'redirect'):
            setup.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.example')
        with patch.object(setup.urllib.request, 'build_opener') as network:
            with self.assertRaises(ValueError):
                setup.discover_models('http://remote.example', 'openai', 'SECRET')
            network.assert_not_called()

    def test_discovery_pagination_keeps_credentials_on_the_same_origin(self):
        pages = iter([{'data': [{'id': 'a'}], 'has_more': True, 'last_id': 'a'},
                      {'data': [{'id': 'b'}], 'has_more': False}])
        targets = []
        def reply(request, timeout):
            targets.append(request.full_url)
            return io.BytesIO(json.dumps(next(pages)).encode())
        with patch.object(setup.urllib.request, 'build_opener',
                          return_value=SimpleNamespace(open=reply)):
            self.assertEqual([m['id'] for m in setup.discover_models(
                'https://remote.example', 'anthropic', 'SECRET')], ['a', 'b'])
        self.assertEqual(targets, ['https://remote.example/v1/models',
                                  'https://remote.example/v1/models?after_id=a'])

    def test_root_and_noninteractive_input_are_refused(self):
        with patch.object(setup.os, 'geteuid', return_value=1000):
            with self.assertRaisesRegex(ValueError, 'sudo'):
                setup.check_host()
        with patch.object(setup.sys.stdin, 'isatty', return_value=False):
            with self.assertRaisesRegex(ValueError, 'interactively'):
                setup.add_provider('openai')

    def test_failed_secret_creation_leaves_no_provider_record(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(setup, 'STATE', Path(directory)), \
                patch.object(setup.sys.stdin, 'isatty', return_value=True), \
                patch.object(setup, 'provider_settings', return_value={'secret': 'example', 'model': {'id': 'model-a'}}), \
                patch('builtins.input', return_value=''), \
                patch.object(setup.getpass, 'getpass', return_value='SECRET_SENTINEL'), \
                patch.object(setup, 'service', return_value=SimpleNamespace(returncode=1)):
            with self.assertRaisesRegex(ValueError, 'secret creation failed'):
                setup.add_provider('openai')
            self.assertFalse((Path(directory) / 'provider-openai.json').exists())


if __name__ == '__main__':
    unittest.main()
