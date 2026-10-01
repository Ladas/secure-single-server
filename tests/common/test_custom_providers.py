"""Additional providers retain native APIs, credentials and independent budgets."""
import json
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'scripts/common'), str(ROOT / 'tests/common')]
import provider_config
import provider_manage
import quota_config
import tempfile
from unittest.mock import patch
import quota_manage
from test_quota_manage import template

CUSTOM = {'team': {'openai_url': 'https://openai.example.test/v1',
                   'anthropic_url': 'https://messages.example.test', 'secret': 'team-v1'}}


class CustomProvidersTest(unittest.TestCase):
    def test_native_routes_credentials_and_quota_do_not_replace_builtin_providers(self):
        for scenario in ('all-in-one', 'remote-gateway'):
            config = provider_config.render(template(scenario), vllm=True, openai=True,
                                            anthropic=False, custom=CUSTOM)
            self.assertEqual(config['listeners'], template(scenario)['listeners'])
            text = json.dumps(config)
            self.assertIn('api.openai.com', text)
            self.assertIn('praxis-vllm:8000', text)
            self.assertIn('openai.example.test', text)
            self.assertIn('messages.example.test', text)
            self.assertIn('/providers/team/v1/models', text)
            self.assertIn('CUSTOM_TEAM_API_KEY', text)
            self.assertNotIn('team-v1', text)  # Secret names belong in the unit only.
            self.assertTrue(quota_manage.listing(config, provider='team')['rules'])
            for chain in config['filter_chains']:
                routes = next(f['routes'] for f in chain['filters'] if f['filter'] == 'router')
                keys = [(r.get('path'), r.get('path_prefix')) for r in routes]
                self.assertEqual(len(keys), len(set(keys)))

    def test_provider_edits_preserve_custom_routes_and_quota_overrides(self):
        base = template()
        state = {'vllm': True, 'openai_secret': '', 'anthropic_secret': '', 'custom_providers': CUSTOM}
        overrides = {'team-openai-rolling-day': 50000}
        installed = quota_config.apply(provider_config.render(base, vllm=True, openai=False,
                                       anthropic=False, custom=CUSTOM), overrides)
        updated = provider_manage.updated_config(base, installed, state, {**state, 'openai_secret': 'new'},
                                                  overrides=overrides)
        self.assertEqual(quota_config.rules(updated)['team-openai-rolling-day']['capacity'], 50000)
        self.assertIn('openai.example.test', json.dumps(updated))

    def test_upgrade_retains_custom_secret_mounts_and_endpoints(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'shared-gateway.yaml').write_text(json.dumps(template()))
            (root / 'praxis.container').write_text('[Container]\nImage=fixture\n')
            previous = root / 'previous.json'
            previous.write_text(json.dumps({'custom_providers': CUSTOM}))
            with patch.object(sys, 'argv', ['provider_config', '--directory', directory, '--vllm',
                                           '--existing-state', str(previous)]):
                provider_config.main()
            self.assertIn('Secret=team-v1,type=env,target=CUSTOM_TEAM_API_KEY', (root / 'praxis.container').read_text())
            self.assertEqual(json.loads((root / 'providers.json').read_text())['custom_providers'], CUSTOM)

    def test_custom_only_provider_enables_disabled_listener(self):
        config = provider_config.render(template(), vllm=False, openai=False, anthropic=False, custom=CUSTOM)
        self.assertNotIn('static_response', json.dumps(config))

    def test_endpoint_cannot_include_credentials_or_arbitrary_paths(self):
        for url in ('http://example.test', 'https://key@example.test/v1',
                    'https://example.test/v1?key=secret', 'https://example.test/api/v1', 'https://example.test:0'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                provider_config.render(template(), vllm=True, openai=False, anthropic=False,
                    custom={'team': {**CUSTOM['team'], 'openai_url': url}})


if __name__ == '__main__':
    unittest.main()
