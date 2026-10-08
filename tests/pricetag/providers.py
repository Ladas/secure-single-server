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
    def test_refresh_replaces_only_pricetag_models_and_preserves_security_boundary(self):
        import yaml
        from provider_config import render
        old = [
            {'id':'openai/gpt-6-luna','provider':'openai','model':'gpt-6-luna',
             'apis':['openai'],'context':1050000,'output':128000},
            {'id':'pricetag/old-model','provider':'pricetag','model':'old-model',
             'apis':['openai'],'context':32768,'output':8192}]
        new = {'id':'pricetag/rits/zai-org/glm-5-3','provider':'pricetag','model':'rits/zai-org/glm-5-3',
               'apis':['anthropic'],'context':262144,'output':65536}
        original = render(yaml.safe_load((ROOT/'configs/all-in-one/shared-gateway.yaml').read_text()),
            vllm=False, openai=True, anthropic=False, custom={'pricetag':{'openai_url':'https://old.example'}})
        deployed = gateway(original, old, origins=['https://gateway.example:8443'])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); state=root/'inputs'; deploy=root/'deploy'
            state.mkdir(); (deploy/'gateway').mkdir(parents=True)
            (state/'providers.json').write_text(json.dumps(original))
            (deploy/'models.json').write_text(json.dumps(old))
            (deploy/'gateway/gateway.json').write_text(json.dumps(deployed))
            (deploy/'price-sources.json').write_text(json.dumps({m['id']:m['model'] for m in old}))
            settings={'models':[new], 'urls':{'anthropic':'https://new.example'}, 'messages_auth':'x-api-key'}
            with patch.object(setup, 'STATE', state), patch.object(setup, 'DEPLOY', deploy), \
                    contextlib.redirect_stdout(io.StringIO()):
                files=setup.refresh_model_files(settings)
            models=json.loads(files[deploy/'models.json'])
            self.assertEqual(models,[old[0],new])
            updated=json.loads(files[deploy/'gateway/gateway.json'])
            self.assertEqual(updated['listeners'],deployed['listeners'])
            before={c['name']:c for c in deployed['filter_chains']}
            after={c['name']:c for c in updated['filter_chains']}
            for name in ('edge','callout','validation','dashboard'):
                self.assertEqual(after[name],before[name])
            auth_before=[f for f in before['authenticated']['filters'] if f['filter']=='manual_jwt']
            auth_after=[f for f in after['authenticated']['filters'] if f['filter']=='manual_jwt']
            self.assertEqual(auth_after,auth_before)
            public=next(f for f in after['authenticated']['filters'] if f['filter']=='static_response')
            self.assertEqual([m['id'] for m in json.loads(public['body'])['data']],[old[0]['id'],new['id']])
            serialized=json.dumps(updated)
            self.assertNotIn('old-model',serialized)
            self.assertNotIn('old.example',serialized)
            self.assertNotIn('token_rate_limit',serialized)
            self.assertIn('CUSTOM_PRICETAG_API_KEY',serialized)
            self.assertIn('api.openai.com',serialized)

    def test_migration_prices_only_insert_missing_aliases(self):
        sql=setup.migration_prices([{'id':'pricetag/rits/zai-org/glm-5-3',
                                     'model':'rits/zai-org/glm-5-3'}])
        self.assertTrue(sql.startswith('BEGIN;'))
        self.assertIn('ON CONFLICT(model) DO NOTHING',sql)
        self.assertIn('usage_events',sql)
        self.assertNotIn('DELETE ',sql)
        self.assertNotIn('UPDATE ',sql)
        self.assertNotIn('quota',sql)

    def test_messages_bearer_header_is_used_for_discovery_and_inference(self):
        seen = []
        def reply(request, timeout):
            seen.append(request)
            return io.BytesIO(b'{"data":[]}')
        with patch.object(setup, 'MESSAGES_AUTH', 'bearer'), \
                patch.object(setup.urllib.request, 'build_opener', return_value=SimpleNamespace(open=reply)):
            setup.discover_models('https://example.com', 'anthropic', 'SECRET')
        self.assertEqual(seen[0].get_header('Authorization'), 'Bearer SECRET')
        self.assertIsNone(seen[0].get_header('X-api-key'))
        config = {'filter_chains':[{'filters':[{'filter':'credential_injection','clusters':[
            {'name':'pricetag-anthropic','header':'x-api-key','env_var':'CUSTOM_PRICETAG_API_KEY'},
            {'name':'openai','header':'Authorization','header_prefix':'Bearer ','env_var':'OPENAI_API_KEY'}]}]}]}
        setup.messages_auth(config, 'bearer')
        credentials = config['filter_chains'][0]['filters'][0]['clusters']
        self.assertEqual(credentials[0]['header'], 'Authorization')
        self.assertEqual(credentials[0]['header_prefix'], 'Bearer ')
        self.assertEqual(credentials[1]['env_var'], 'OPENAI_API_KEY')
        setup.messages_auth(config, 'x-api-key')
        self.assertEqual(credentials[0]['header'], 'x-api-key')
        self.assertEqual(credentials[0]['header_prefix'], '')

    def test_catalog_diagnostic_checks_both_headers_without_storing_key(self):
        seen = []
        def discover(url, api, key):
            seen.append((url, api, setup.CATALOG_AUTH))
            if setup.CATALOG_AUTH == 'x-api-key':
                raise ValueError('model discovery returned HTTP 401')
            return [{'id':'model'}]
        with patch.object(setup, 'discover_models', side_effect=discover), \
                patch.object(setup, 'service') as service, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            setup.diagnose_catalog_auth({'anthropic':'https://example.com',
                'openai':'https://example.com/v1'}, 'SECRET')
        self.assertEqual([entry[2] for entry in seen], ['x-api-key','bearer'])
        service.assert_not_called()
        self.assertIn('HTTP 401', output.getvalue())
        self.assertIn('bearer: accepted', output.getvalue())
        self.assertNotIn('SECRET', output.getvalue())
        self.assertEqual(setup.CATALOG_AUTH, 'native')

    def test_openai_replacement_preserves_other_provider(self):
        config = {'filter_chains':[{'filters':[{'filter':'load_balancer','clusters':[
            {'name':'openai','endpoints':['old:443']},
            {'name':'pricetag-openai','endpoints':['untouched:443']}]}]}]}
        updated = setup.replace_endpoints(config, {'openai':'https://api.openai.com/v1'}, name='openai')
        clusters = updated['filter_chains'][0]['filters'][0]['clusters']
        self.assertEqual(clusters[0]['endpoints'], ['api.openai.com:443'])
        self.assertEqual(clusters[1]['endpoints'], ['untouched:443'])

    def test_inference_diagnostic_bounds_request_and_redacts_errors(self):
        requests = []
        def reply(request, timeout):
            requests.append(request)
            self.assertEqual(request.full_url, 'https://example.com/v1/messages')
            self.assertEqual(timeout, 30)
            body = json.loads(request.data)
            self.assertEqual(body['model'], 'rits/zai-org/glm-5-3')
            self.assertEqual(body['max_tokens'], 16)
            self.assertNotIn('SECRET', request.data.decode())
            if request.get_header('X-api-key'):
                raise setup.urllib.error.HTTPError(request.full_url, 401, 'SECRET', {},
                    io.BytesIO(b'{"error":{"type":"authentication_error","message":"SECRET"}}'))
            return SimpleNamespace(status=200, headers={'Content-Type':'application/json'},
                                   read=lambda n: b'{}', close=lambda: None)
        with patch.object(setup.urllib.request, 'build_opener', return_value=SimpleNamespace(open=reply)), \
                patch.object(setup, 'service') as service, contextlib.redirect_stdout(io.StringIO()) as output:
            setup.diagnose_inference({'anthropic':'https://example.com'}, 'SECRET',
                                     ('anthropic','rits/zai-org/glm-5-3'))
        service.assert_not_called()
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[1].get_header('Authorization'), 'Bearer SECRET')
        self.assertIn('HTTP 401', output.getvalue())
        self.assertIn('bearer: HTTP 200', output.getvalue())
        self.assertNotIn('SECRET', output.getvalue())

    def test_explicit_glm_pin_survives_incomplete_catalog(self):
        pins = {('anthropic', 'rits/zai-org/glm-5-3')}
        with patch.object(setup, 'PINNED_MODELS', pins), \
                patch.object(setup, 'discover_models', return_value=[]), \
                patch.object(setup, 'service', return_value=SimpleNamespace(returncode=1)), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            settings = setup.provider_settings('pricetag', 'anthropic', 'https://example.com', 'SECRET')
        self.assertEqual(settings['models'], [{'id':'pricetag/rits/zai-org/glm-5-3',
            'provider':'pricetag','model':'rits/zai-org/glm-5-3','apis':['anthropic'],
            'context':262144,'output':65536}])
        self.assertEqual(settings['unverified_models'], ['rits/zai-org/glm-5-3'])
        self.assertIn('not advertised',output.getvalue())
        self.assertNotIn('SECRET',output.getvalue())

    def test_catalog_header_override_keeps_key_out_of_body(self):
        for auth,header in [('bearer','Authorization'),('x-api-key','X-api-key')]:
            def reply(request,timeout):
                self.assertEqual(request.get_header(header), 'Bearer SECRET' if auth=='bearer' else 'SECRET')
                self.assertEqual(request.get_header('Anthropic-version'),'2023-06-01')
                self.assertIsNone(request.data)
                return io.BytesIO(b'{"data":[]}')
            with patch.object(setup, 'CATALOG_AUTH', auth), \
                    patch.object(setup.urllib.request,'build_opener',return_value=SimpleNamespace(open=reply)):
                self.assertEqual(setup.discover_models('https://example.com','anthropic','SECRET'),[])

    def test_missing_catalog_requires_explicit_fallback(self):
        for status in (404, 405, 501):
            def reject(request, timeout):
                raise setup.urllib.error.HTTPError(request.full_url, status, 'SECRET', {}, io.BytesIO(b'SECRET'))
            with self.subTest(status=status), \
                    patch.object(setup.urllib.request, 'build_opener', return_value=SimpleNamespace(open=reject)), \
                    patch.object(setup, 'service', return_value=SimpleNamespace(returncode=1)), \
                    patch.object(setup, 'ALLOW_UNVERIFIED_MODELS', False):
                with self.assertRaisesRegex(ValueError, 'allow-unverified-models'):
                    setup.provider_settings('pricetag', 'openai', 'https://example.com/v1', 'SECRET')
                with patch.object(setup, 'ALLOW_UNVERIFIED_MODELS', True), contextlib.redirect_stdout(io.StringIO()) as out:
                    settings = setup.provider_settings('pricetag', 'openai', 'https://example.com/v1', 'SECRET')
                self.assertEqual(settings['unverified_apis'], ['openai'])
                self.assertEqual(len(settings['models']), len(setup.PRESETS['openai']))
                self.assertIn('UNVERIFIED', out.getvalue())
                self.assertNotIn('SECRET', out.getvalue())

    def test_discovery_fallback_never_ignores_auth_server_or_tls_failures(self):
        for status in (401, 403, 429, 500, 503):
            def reject(request, timeout):
                raise setup.urllib.error.HTTPError(request.full_url, status, 'SECRET', {}, io.BytesIO(b'SECRET'))
            with self.subTest(status=status), patch.object(setup, 'ALLOW_UNVERIFIED_MODELS', True), \
                    patch.object(setup.urllib.request, 'build_opener', return_value=SimpleNamespace(open=reject)), \
                    patch.object(setup, 'service') as service:
                with self.assertRaisesRegex(ValueError, 'HTTP ' + str(status)):
                    setup.provider_settings('pricetag', 'openai', 'https://example.com', 'SECRET')
                service.assert_not_called()
        with patch.object(setup, 'ALLOW_UNVERIFIED_MODELS', True), \
                patch.object(setup.urllib.request, 'build_opener', return_value=SimpleNamespace(
                    open=lambda *a, **kw: (_ for _ in ()).throw(setup.urllib.error.URLError('TLS failed')))):
            with self.assertRaisesRegex(ValueError, 'discovery failed'):
                setup.provider_settings('pricetag', 'openai', 'https://example.com', 'SECRET')

    def test_active_replacement_changes_only_pricetag_endpoints(self):
        config = {'listeners': ['unchanged'], 'filter_chains': [{'name': 'openai', 'filters': [
            {'filter': 'manual_jwt', 'registry_file': 'unchanged'},
            {'filter': 'load_balancer', 'clusters': [
                {'name': 'openai', 'endpoints': ['api.openai.com:443']},
                {'name': 'pricetag-openai', 'weight': 2, 'endpoints': ['old:443'],
                 'http': {'authority': 'old', 'application_provider': 'pricetag-openai'},
                 'tls': {'sni': 'old'}}]}]}]}
        updated = setup.replace_endpoints(config, {'openai': 'https://new.example/v1'})
        self.assertEqual(config['filter_chains'][0]['filters'][1]['clusters'][1]['endpoints'], ['old:443'])
        expected = json.loads(json.dumps(config))
        expected['filter_chains'][0]['filters'][1]['clusters'][1].update(
            endpoints=['new.example:443'],
            http={'authority': 'new.example', 'application_provider': 'pricetag-openai'},
            tls={'sni': 'new.example'})
        self.assertEqual(updated, expected)
        with self.assertRaisesRegex(ValueError, 'cluster'):
            setup.replace_endpoints(config, {'anthropic': 'https://new.example'})

    def test_active_replacement_requires_existing_models_and_limits(self):
        old = [{'id':'pricetag/model', 'provider':'pricetag', 'model':'model',
                'apis':['openai'], 'context':1000, 'output':100}]
        setup.check_replacement_models(old, {'models': old})
        for models in ([], [{**old[0], 'apis':['anthropic']}], [{**old[0], 'context':500}]):
            with self.assertRaisesRegex(ValueError, 'existing model'):
                setup.check_replacement_models(old, {'models':models})

    def test_active_replacement_does_not_silently_ignore_new_pin(self):
        old = [{'id':'pricetag/model', 'provider':'pricetag', 'model':'model',
                'apis':['openai'], 'context':1000, 'output':100}]
        with patch.object(setup, 'PINNED_MODELS', {('anthropic', 'rits/zai-org/glm-5-3')}):
            with self.assertRaisesRegex(ValueError, 'does not add models'):
                setup.check_replacement_models(old, {'models':old})

    def test_active_replacement_rolls_back_all_files_on_restart_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory)
            a,b=state/'gateway.json',state/'gateway.container'
            a.write_text('old config'); b.write_text('old unit')
            a.chmod(0o640); b.chmod(0o644)
            with patch.object(setup, 'STATE', state), \
                    patch.object(setup, 'relabel'), \
                    patch.object(setup, 'activate_gateway', side_effect=[ValueError('restart failed'),None]), \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError, 'restored'):
                    setup.install_replacement({a:b'new config', b:b'new unit'})
            self.assertEqual(a.read_text(),'old config')
            self.assertEqual(b.read_text(),'old unit')
            self.assertEqual(a.stat().st_mode & 0o777,0o640)

    def test_replacement_plan_preserves_catalog_and_non_provider_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state, deploy, units = root/'inputs', root/'deploy', root/'units'
            for path in (state, deploy/'gateway', deploy/'quadlets', units/'995'):
                path.mkdir(parents=True)
            models = [{'id':'pricetag/gpt-6-luna', 'provider':'pricetag', 'model':'gpt-6-luna',
                       'apis':['openai'], 'context':1000, 'output':100}]
            (deploy/'models.json').write_text(json.dumps(models))
            config = {'filter_chains':[{'filters':[{'filter':'load_balancer','clusters':[
                {'name':'pricetag-openai', 'endpoints':['old:443'],
                 'http':{'application_provider':'pricetag-openai'}}]}]}]}
            for path in (deploy/'gateway/gateway.json', state/'providers.json'):
                path.write_text(json.dumps(config))
            unit = ('[Container]\nSecret=direct-key,type=env,target=OPENAI_API_KEY\n'
                    'Secret=old-key,type=env,target=CUSTOM_PRICETAG_API_KEY\n')
            for path in (deploy/'quadlets/pricetag-gateway.container',
                         units/'995/pricetag-gateway.container', state/'provider-secrets.container'):
                path.write_text(unit)
            settings = {'models':models, 'urls':{'openai':'https://new.example/v1'}, 'secret':'new-key'}
            with patch.object(setup, 'STATE', state), patch.object(setup, 'DEPLOY', deploy), \
                    patch.object(setup, 'USER_UNITS', units), \
                    patch.object(setup.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=995)):
                files = setup.replacement_files(settings)
            self.assertEqual(len(files), 6)
            self.assertNotIn(deploy/'models.json', files)
            self.assertEqual(json.loads((deploy/'gateway/gateway.json').read_text()), config)
            saved = json.loads(files[state/'provider-pricetag.json'])
            self.assertEqual(saved['models'], models)
            self.assertIn(b'Secret=direct-key,type=env,target=OPENAI_API_KEY',
                          files[units/'995/pricetag-gateway.container'])
            self.assertIn(b'Secret=new-key,type=env,target=CUSTOM_PRICETAG_API_KEY',
                          files[units/'995/pricetag-gateway.container'])

    def test_active_host_guard_requires_explicit_replacement_and_completed_bootstrap(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(setup, 'DEPLOY', Path(directory)), \
                patch.object(setup, 'STATE', Path(directory)), \
                patch.object(setup.os, 'geteuid', return_value=0):
            with self.assertRaisesRegex(ValueError, 'Already prepared'):
                setup.check_host()
            with self.assertRaisesRegex(ValueError, 'Already prepared'):
                setup.check_host(allow_active=True)

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
            self.assertEqual(len(models), 10)
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
