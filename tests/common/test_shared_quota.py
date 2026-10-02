"""Shared Valkey limits must be one budget across API listeners."""
import copy
import json
from datetime import datetime, timezone
import sys
import unittest
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'scripts/common'), str(ROOT / 'tests/common')]
import provider_config
import provider_manage
import quota_config
import quota_manage
import quota_status
import quota_share
from test_quota_manage import template


class SharedQuotaTest(unittest.TestCase):
    def test_shared_quota_command_retains_the_remote_inference_endpoint(self):
        endpoint = '10.0.1.10:8000'
        state = dict(vllm=True, vllm_endpoint=endpoint, openai_secret='', anthropic_secret='')
        import yaml
        source = yaml.safe_load((ROOT / 'configs/all-in-one/shared-gateway-valkey.yaml').read_text())
        installed = provider_config.render(source, vllm=True, openai=False,
                                           anthropic=False, vllm_endpoint=endpoint)
        read_text = Path.read_text
        def read(path, *args, **kwargs):
            if str(path).startswith('/etc/containers/systemd/users/'):
                return '[Container]\n'
            return read_text(path, *args, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content in {'shared-gateway.profile': 'valkey', 'gateway.scenario': 'all-in-one',
                    'providers.json': json.dumps(state), 'shared-gateway.yaml': json.dumps(installed)}.items():
                (root / name).write_text(content)
            with patch.object(provider_manage, 'CONFIG', root), patch.object(Path, 'read_text', read), \
                    patch.object(provider_manage.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=1234, pw_gid=1234)), \
                    patch.object(sys, 'argv', ['providers', 'enable', 'vllm', '--shared-quota', '--capacity', '10000000']), \
                    patch.object(provider_manage, 'service'), patch.object(quota_share, 'prepare'), \
                    patch.object(provider_manage, 'transaction') as transaction:
                provider_manage.main()
            changes = transaction.call_args.args[0]
            applied = json.loads(changes[root / 'providers.json'])
            self.assertEqual(applied['vllm_endpoint'], endpoint)
            config = json.loads(changes[root / 'shared-gateway.yaml'])
            clusters = [c for chain in config['filter_chains'] for f in chain['filters']
                        if f['filter'] == 'load_balancer' for c in f['clusters'] if c['name'] == 'vllm']
            self.assertTrue(clusters)
            self.assertTrue(all(c['endpoints'] == [endpoint] for c in clusters))

    def config(self, scenario='all-in-one'):
        source = template(scenario)
        for chain in source['filter_chains']:
            for f in chain['filters']:
                if f['filter'] == 'token_rate_limit':
                    f['backend'] = {'kind': 'valkey', 'url': '${TOKEN_RATE_LIMIT_VALKEY_URL}',
                                    'namespace': 'secure-single-server:limits:' + f['rules'][0]['name'].split('-')[0]}
        return provider_config.render(source, vllm=True, openai=True, anthropic=True, shared_vllm=True)

    def test_one_budget_lists_once_and_capacity_updates_both_listeners(self):
        for scenario in ('all-in-one', 'remote-gateway'):
            source = self.config(scenario)
            report = quota_manage.listing(source, provider='vllm')
            self.assertEqual([r['rule'] for r in report['rules']], ['vllm-rolling-day'])
            updated = quota_config.apply(source, {'vllm-rolling-day': 70000})
            found = [f for c in updated['filter_chains'] for f in c['filters']
                     if f['filter'] == 'token_rate_limit' and f['rules'][0]['name'] == 'vllm-rolling-day']
            self.assertEqual(len(found), 2 if scenario == 'all-in-one' else 1)
            self.assertTrue(all(f['rules'][0]['capacity'] == 70000 for f in found))
            self.assertEqual({f['backend']['namespace'] for f in found}, {'secure-single-server:limits:vllm'})
            now = datetime.now(timezone.utc)
            rows = quota_status.summarize(updated, '', now, now, now)
            self.assertEqual(sum(r['rule'] == 'vllm-rolling-day' for r in rows), 1)

    def test_inconsistent_shared_settings_are_rejected(self):
        source = self.config()
        found = [f for c in source['filter_chains'] for f in c['filters']
                 if f['filter'] == 'token_rate_limit' and f['rules'][0]['name'] == 'vllm-rolling-day']
        found[1]['rules'][0]['capacity'] += 1
        with self.assertRaisesRegex(ValueError, 'shared|unique'):
            quota_config.rules(source)

    def test_migration_preserves_original_timestamps_and_retained_estimates(self):
        snapshot = ['1000', '0', ['settled:1:7', '999000', 'expired:2:5', '995000'],
                    ['3', '10|998000', '4', '30|900000']]
        self.assertEqual(quota_share.records(snapshot, 10000, 5000),
                         [[999000, 7], [995000, 5], [998000, 10]])
        with self.assertRaises(ValueError):
            quota_share.records(['1000', '0', ['bad', '999000'], []], 10000, 5000)

    def test_memory_cannot_claim_shared_listeners(self):
        with self.assertRaisesRegex(ValueError, 'Valkey'):
            provider_config.render(template(), vllm=True, openai=False, anthropic=False, shared_vllm=True)


if __name__ == '__main__':
    unittest.main()
