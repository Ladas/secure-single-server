"""Unified model selection preserves provider credentials and quota identities."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'scripts/common'), str(ROOT / 'tests/common')]
import provider_config
import provider_manage
import quota_config
import unified_config
from test_quota_manage import template

MODELS = [
    {'id': 'vllm/qwen3-8b', 'provider': 'vllm', 'model': 'qwen3-8b',
     'apis': ['openai', 'anthropic'], 'context': 16384, 'output': 4096},
    {'id': 'openai/gpt-5.4-mini', 'provider': 'openai', 'model': 'gpt-5.4-mini',
     'apis': ['openai'], 'context': 128000, 'output': 8192},
    {'id': 'team/gpt-5.4-mini', 'provider': 'team', 'model': 'gpt-5.4-mini',
     'apis': ['openai'], 'context': 128000, 'output': 8192},
    {'id': 'team/claude-sonnet-5', 'provider': 'team', 'model': 'claude-sonnet-5',
     'apis': ['anthropic'], 'context': 128000, 'output': 8192},
]
CUSTOM = {'team': {'openai_url': 'https://openai.example.test/v1',
                   'anthropic_url': 'https://messages.example.test', 'secret': 'team-v1'}}


class UnifiedTest(unittest.TestCase):
    def test_unified_provider_edit_keeps_separate_inference_host(self):
        state = {'vllm': True, 'vllm_endpoint': '10.0.1.10:8000', 'openai_secret': '',
                 'anthropic_secret': '', 'models': MODELS}
        original = provider_config.render(template(), vllm=True, openai=False, anthropic=False,
                                          vllm_endpoint=state['vllm_endpoint'], models=MODELS)
        config = provider_manage.updated_config(template(), original, state,
                                                 {**state, 'openai_secret': 'new-reference'})
        for chain in config['filter_chains']:
            cluster = next(c for f in chain['filters'] if f['filter'] == 'load_balancer'
                           for c in f['clusters'] if c['name'] == 'vllm')
            self.assertEqual(cluster['endpoints'], ['10.0.1.10:8000'])
            self.assertEqual(cluster['http'], {'authority': '10.0.1.10:8000',
                                               'application_provider': 'vllm'})

    def render(self, **kwargs):
        return provider_config.render(template(), vllm=True, openai=True, anthropic=False,
                                      custom=CUSTOM, models=MODELS, **kwargs)

    def test_hide_reasoning_targets_only_local_responses_and_is_reversible(self):
        previous = {'vllm': True, 'openai_secret': 'synthetic-name', 'anthropic_secret': '',
                    'custom_providers': CUSTOM, 'models': MODELS}
        original = self.render()
        selected = {**previous, 'hide_vllm_reasoning': True}
        config = provider_manage.updated_config(template(), original, previous, selected)
        additions = [f for c in config['filter_chains'] for f in c['filters']
                     if f.get('request_add') == [{'pointer': '/include_reasoning', 'value': False}]]
        self.assertEqual(len(additions), 1)
        self.assertEqual(additions[0]['conditions'], [{'when': {'methods': ['POST'],
            'path': '/v1/responses', 'headers': {unified_config.MODEL_HEADER: 'vllm/qwen3-8b'}}}])
        self.assertEqual(quota_config.rules(original), quota_config.rules(config))
        self.assertIsNone(provider_manage.updated_config(template(), config, selected, selected))
        restored = provider_manage.updated_config(template(), config, selected, previous)
        self.assertEqual(restored, original)

    def test_routes_are_exact_and_catalogs_follow_enabled_connections(self):
        config = self.render()
        self.assertEqual(config['listeners'], template()['listeners'])
        for chain in config['filter_chains']:
            catalog = next(f for f in chain['filters'] if f['filter'] == 'static_response')
            advertised = [m['id'] for m in json.loads(catalog['body'])['data']]
            self.assertEqual(advertised, [m['id'] for m in MODELS if chain['name'] in m['apis']])
            router = next(f for f in chain['filters'] if f['filter'] == 'router')
            self.assertTrue(all('path' in r and 'headers' in r for r in router['routes']))
            self.assertNotIn('/providers/', json.dumps(router))
        config = provider_config.render(template(), vllm=True, openai=False, anthropic=False, models=MODELS)
        for chain in config['filter_chains']:
            body = next(f['body'] for f in chain['filters'] if f['filter'] == 'static_response')
            self.assertEqual([m['id'] for m in json.loads(body)['data']], ['vllm/qwen3-8b'])

    def test_quota_names_backends_and_credentials_survive_unification(self):
        legacy = provider_config.render(template(), vllm=True, openai=True, anthropic=False, custom=CUSTOM)
        config = self.render()
        self.assertEqual(quota_config.rules(config), quota_config.rules(legacy))
        for source, target in zip(legacy['filter_chains'], config['filter_chains']):
            for f in target['filters']:
                if f['filter'] == 'load_balancer':
                    for c in f['clusters']:
                        c['http'].pop('application_provider')
                        if not c['http']:
                            c.pop('http')
            for name in ('credential_injection', 'load_balancer'):
                self.assertEqual([f for f in source['filters'] if f['filter'] == name],
                                 [f for f in target['filters'] if f['filter'] == name])
        self.assertNotIn('team-v1', json.dumps(config))

    def test_catalog_rejects_ambiguous_ids_and_invalid_limits(self):
        for change in ({'id': MODELS[0]['id']}, {'context': 10}, {'apis': ['bogus']},
                       {'provider': '../bad'}, {'model': 'bad\nvalue'}, {'extra': 'ignored'}):
            models = copy.deepcopy(MODELS)
            models[1].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                unified_config.validate(models)

    def test_disabled_api_has_empty_catalog_and_no_upstreams(self):
        config = provider_config.render(template(), vllm=False, openai=True, anthropic=False, models=MODELS)
        chain = next(c for c in config['filter_chains'] if c['name'] == 'anthropic')
        responses = [f for f in chain['filters'] if f['filter'] == 'static_response']
        self.assertEqual(json.loads(responses[0]['body'])['data'], [])
        self.assertEqual(responses[-1]['status'], 404)
        self.assertFalse(any(f['filter'] in ('load_balancer', 'router') for f in chain['filters']))

    def test_provider_changes_preserve_unified_catalog_and_saved_capacities(self):
        previous = {'vllm': True, 'openai_secret': '', 'anthropic_secret': '', 'models': MODELS}
        installed = provider_config.render(template(), vllm=True, openai=False, anthropic=False, models=MODELS)
        overrides = {'vllm-openai-rolling-day': 10000000, 'openai-rolling-day': 2000000}
        installed = quota_config.apply(installed, overrides)
        selected = {**previous, 'openai_secret': 'synthetic-key-reference'}
        changed = provider_manage.updated_config(template(), installed, previous, selected, overrides=overrides)
        self.assertEqual(quota_config.rules(changed)['openai-rolling-day']['capacity'], 2000000)
        self.assertEqual(quota_config.rules(changed)['vllm-openai-rolling-day']['capacity'], 10000000)
        self.assertEqual([m['id'] for m in unified_config.active(MODELS, changed, 'openai')],
                         ['vllm/qwen3-8b', 'openai/gpt-5.4-mini'])
        self.assertIsNone(provider_manage.updated_config(template(), changed, selected, selected, overrides=overrides))


if __name__ == '__main__':
    unittest.main()
