#!/usr/bin/env python3
"""Contract tests for browser-controlled provider configuration."""
import copy
from contextlib import nullcontext
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'scripts/pricetag'), str(ROOT / 'scripts/common')]
import gateway_management as management
from gateway import render


class Contract(unittest.TestCase):
    def setUp(self):
        self.allowed = ['https://provider.example']
        self.config = {'providers': [{'name': 'external', 'urls': {
            'openai': 'https://provider.example/v1', 'anthropic': 'https://provider.example'},
            'messages_auth': 'x-api-key'}], 'models': [{
                'id': 'external/demo', 'provider': 'external', 'model': 'demo',
                'apis': ['openai', 'anthropic'], 'context': 32768, 'output': 4096}]}

    def test_valid_config_compiles_routing_and_keeps_authentication(self):
        validated = management.validate(self.config, self.allowed)
        config = render(management.native_inputs(validated), validated['models'])
        for chain in config['filter_chains']:
            if chain['name'] in ('openai', 'anthropic'):
                filters = [f['filter'] for f in chain['filters']]
                self.assertIn('api_key_auth', filters)
                self.assertIn('external_metering', filters)
                self.assertIn('credential_injection', filters)
        native = management.native_inputs(validated)
        for chain in native['filter_chains']:
            credential = next(f for f in chain['filters'] if f['filter'] == 'credential_injection')['clusters'][0]
            self.assertEqual(credential['header_prefix'], 'Bearer ' if chain['name'] == 'openai' else '')
            self.assertNotIn('prefix', credential)

    def test_rejects_unapproved_origins_and_arbitrary_fields(self):
        for address in ['https://evil.example/v1', 'http://169.254.169.254/v1',
                        'https://user:password@provider.example/v1',
                        'https://provider.example/v1?target=metadata',
                        'https://provider.example/../../admin']:
            value = copy.deepcopy(self.config)
            value['providers'][0]['urls']['openai'] = address
            with self.assertRaises(ValueError):
                management.validate(value, self.allowed)
        for field in ['filters', 'file', 'command', 'secret']:
            value = copy.deepcopy(self.config)
            value[field] = 'untrusted'
            with self.assertRaises(ValueError):
                management.validate(value, self.allowed)

    def test_stale_update_cannot_overwrite_current_config(self):
        with self.assertRaises(management.Conflict):
            management.check_update(self.config, 'stale', self.config, self.allowed)
        self.assertEqual(management.check_update(self.config, management.revision(self.config),
                                                self.config, self.allowed), self.config)

    def test_limits_and_provider_association_are_validated(self):
        for field, value in [('provider', 'unknown'), ('context', 100), ('output', -1), ('id', 'demo')]:
            invalid = copy.deepcopy(self.config)
            invalid['models'][0][field] = value
            with self.assertRaises(ValueError):
                management.validate(invalid, self.allowed)


class Activation(Contract):
    def test_update_preserves_public_security_configuration(self):
        initial = management.validate(self.config, self.allowed)
        current = render(management.native_inputs(initial), initial['models'], ['https://gateway.example'])
        current['listeners'][0]['address'] = '192.0.2.5:8443'
        edited = copy.deepcopy(initial)
        edited['models'][0]['id'] = 'external/new-alias'
        result = management.merge_gateway(current, edited)
        self.assertEqual(result['listeners'], current['listeners'])
        self.assertEqual(next(c for c in result['filter_chains'] if c['name'] == 'dashboard'),
                         next(c for c in current['filter_chains'] if c['name'] == 'dashboard'))
        for value in (current, result):
            edge = next(c for c in value['filter_chains'] if c['name'] == 'edge')
            for f in edge['filters']:
                if f['filter'] == 'static_response' and f.get('status') == 200:
                    f['body'] = '<catalog>'
        self.assertEqual(next(c for c in result['filter_chains'] if c['name'] == 'edge'),
                         next(c for c in current['filter_chains'] if c['name'] == 'edge'))

    def test_credentials_are_write_only_and_revision_checked_before_activation(self):
        class Backend:
            def __init__(inner): inner.calls = []
            def lock(inner): return nullcontext()
            def read(inner): return self.config
            def activate(inner, document, credentials): inner.calls.append(credentials)
        backend = Backend()
        engine = management.Engine(backend, self.allowed)
        payload = {'revision': management.revision(self.config), 'configuration': self.config,
                   'credentials': {'external': 'synthetic-test-key'}}
        result = engine('PUT', '/config', payload)
        self.assertNotIn('synthetic-test-key', str(result))
        self.assertEqual(backend.calls, [{'external': 'synthetic-test-key'}])
        payload['revision'] = 'outdated'
        with self.assertRaises(management.Conflict): engine('PUT', '/config', payload)
        self.assertEqual(len(backend.calls), 1)


if __name__ == '__main__':
    unittest.main()
