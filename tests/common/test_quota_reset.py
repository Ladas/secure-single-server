"""Selective reset never changes unrelated ledgers or configured capacities."""
import copy
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/common'))
import provider_config
import quota_reset
import quota_status
from test_quota_manage import template


class ResetTest(unittest.TestCase):
    def setUp(self):
        self.config = provider_config.render(template(), vllm=True, openai=True, anthropic=True)
        for chain in self.config['filter_chains']:
            for item in chain['filters']:
                if item['filter'] == 'token_rate_limit':
                    item['backend'] = {'kind': 'valkey', 'url': '${TOKEN_RATE_LIMIT_VALKEY_URL}',
                                       'namespace': 'secure-single-server:limits:' + item['rules'][0]['name']}

    def test_preview_unknown_and_unsupported_rules_do_not_touch_services(self):
        with patch.object(quota_status, 'service') as service, redirect_stdout(io.StringIO()):
            quota_reset.reset(self.config, names=['openai-rolling-day'])
            with self.assertRaisesRegex(ValueError, 'unknown'):
                quota_reset.reset(self.config, names=['openai-rolling-day', 'missing'], apply=True)
            with self.assertRaisesRegex(ValueError, 'no matching'):
                quota_reset.reset(self.config, provider='missing', apply=True)
            for chain in self.config['filter_chains']:
                for item in chain['filters']:
                    if item['filter'] == 'token_rate_limit':
                        item['backend'] = {'kind': 'memory'}
            with self.assertRaisesRegex(ValueError, 'Valkey'):
                quota_reset.reset(self.config, provider='vllm', apply=True)
            service.assert_not_called()

    def test_multiple_selection_resets_exact_keys_after_stop_then_restarts(self):
        before = copy.deepcopy(self.config)
        events = []
        query = Mock(side_effect=lambda *args: events.append(('reset', args)) or '2')
        with patch.object(quota_status, 'service', return_value=json.dumps('image@' + quota_status.LEDGER_IMAGE)), \
                patch.object(quota_status, 'valkey_client', return_value=query), \
                patch.object(quota_reset.provider_manage, 'service', side_effect=lambda *a: events.append(('stop', a))), \
                patch.object(quota_reset.provider_manage, 'restart', side_effect=lambda: events.append(('restart',))), \
                redirect_stdout(io.StringIO()):
            quota_reset.reset(self.config, names=['openai-rolling-day', 'anthropic-rolling-day'], apply=True)
        self.assertEqual([e[0] for e in events], ['stop', 'reset', 'restart'])
        args = query.call_args.args
        expected = [key for name in ('openai-rolling-day', 'anthropic-rolling-day')
                    for key in quota_status.valkey_keys('secure-single-server:limits:' + name, name)]
        self.assertEqual(args[2:], ('4', *expected))
        self.assertEqual(self.config, before)

    def test_restart_after_reset_failure_and_reject_unqualified_image(self):
        with patch.object(quota_status, 'service', return_value=json.dumps('image@' + quota_status.LEDGER_IMAGE)), \
                patch.object(quota_status, 'valkey_client', return_value=Mock(side_effect=ValueError('failed'))), \
                patch.object(quota_reset.provider_manage, 'service') as stop, \
                patch.object(quota_reset.provider_manage, 'restart') as restart, redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'failed'):
                quota_reset.reset(self.config, provider='vllm', apply=True)
            stop.assert_called_once()
            restart.assert_called_once()
        with patch.object(quota_status, 'service', return_value='"unknown"'), \
                patch.object(quota_reset.provider_manage, 'service') as stop, redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'not qualified'):
                quota_reset.reset(self.config, provider='vllm', apply=True)
            stop.assert_not_called()


if __name__ == '__main__':
    unittest.main()
