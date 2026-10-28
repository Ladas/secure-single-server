#!/usr/bin/env python3
import base64
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'scripts/pricetag'), str(ROOT / 'scripts/common')]
from gateway_management import native_inputs
from gateway_management_backend import Backend
from gateway import render


class Activation(unittest.TestCase):
    def test_secret_stdin_and_bounded_file_update(self):
        document = {'providers': [{'name': 'external', 'urls': {'openai': 'https://provider.example/v1'},
                                   'messages_auth': 'x-api-key'}], 'models': [{
            'id': 'external/test', 'model': 'test', 'provider': 'external',
            'apis': ['openai'], 'context': 32000, 'output': 4000}]}
        gateway = render(native_inputs(document), document['models'])
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            deploy, units = base / 'deploy', base / 'units'
            for parent in [deploy / 'quadlets', units / '995']:
                parent.mkdir(parents=True)
                (parent / 'pricetag-gateway.container').write_text(
                    '[Container]\nImage=immutable\nSecret=internal,type=mount,target=/run/secrets/internal\n'
                    'Secret=old,type=env,target=CUSTOM_EXTERNAL_API_KEY\n[Service]\nRestart=always\n')
            helper = SimpleNamespace(DEPLOY=deploy, STATE=base, USER_UNITS=units,
                next_secret=Mock(return_value='provider-v2'), service=Mock(return_value=SimpleNamespace(returncode=0)),
                install_replacement=Mock())
            backend = Backend(helper)
            backend.journal = Mock()
            backend.clear_journal = Mock()
            backend.read_json = lambda name: {'external': 'old'} if name == 'provider-secret-refs.json' else gateway
            with patch('gateway_management_backend.pwd.getpwnam', return_value=SimpleNamespace(pw_uid=995)):
                backend.activate(document, {'external': 'synthetic-sensitive-value'})
            self.assertEqual(helper.service.call_args.args, ('podman', 'secret', 'create', 'provider-v2', '-'))
            self.assertEqual(helper.service.call_args.kwargs, {'input': b'synthetic-sensitive-value'})
            files = helper.install_replacement.call_args.args[0]
            self.assertEqual(len(files), 6)
            self.assertNotIn('synthetic-sensitive-value', str(files))
            for parent in [deploy / 'quadlets', units / '995']:
                body = files[parent / 'pricetag-gateway.container'].decode()
                self.assertIn('Secret=provider-v2,type=env,target=CUSTOM_EXTERNAL_API_KEY', body)
                self.assertIn('Secret=internal,type=mount,target=/run/secrets/internal', body)
                self.assertIn('Image=immutable', body)
                self.assertNotIn('Secret=old,', body)
            self.assertEqual(json.loads(files[deploy / 'models.json']), document['models'])
            helper.install_replacement.side_effect = ValueError('activation failed')
            backend.recover = Mock()
            with patch('gateway_management_backend.pwd.getpwnam', return_value=SimpleNamespace(pw_uid=995)):
                with self.assertRaisesRegex(ValueError, 'activation failed'):
                    backend.activate(document, {})
            backend.recover.assert_called_once()



    def test_interrupted_activation_restores_all_targets_before_serving(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'gateway-activation.pending.json').write_text('pending')
            helper = SimpleNamespace(DEPLOY=base, STATE=base, USER_UNITS=base / 'units',
                relabel=Mock(), activate_gateway=Mock())
            backend = Backend(helper)
            paths = {base / str(i) for i in range(6)}
            backend.activation_paths = lambda: paths
            entries = [{'path':str(p),'uid':0,'gid':0,'mode':0o600,
                        'contents':base64.b64encode(b'original').decode()} for p in paths]
            backend.read_json = lambda _: entries
            backend.durable_write = Mock()
            backend.recover()
            self.assertEqual(backend.durable_write.call_count,6)
            helper.activate_gateway.assert_called_once()
            self.assertFalse((base / 'gateway-activation.pending.json').exists())

    def test_failed_recovery_retains_journal_and_rejects_other_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            marker = base / 'gateway-activation.pending.json'
            marker.write_text('pending')
            helper = SimpleNamespace(DEPLOY=base, STATE=base, USER_UNITS=base / 'units',
                relabel=Mock(), activate_gateway=Mock(side_effect=ValueError('unhealthy')))
            backend = Backend(helper)
            paths = {base / str(i) for i in range(6)}
            backend.activation_paths = lambda: paths
            entries = [{'path':str(p),'uid':0,'gid':0,'mode':0o600,
                        'contents':base64.b64encode(b'original').decode()} for p in paths]
            backend.read_json = lambda _: entries
            backend.durable_write = Mock()
            with self.assertRaisesRegex(ValueError,'unhealthy'):backend.recover()
            self.assertTrue(marker.exists())
            backend.durable_write.reset_mock()
            entries[0]['path']='/etc/passwd'
            with self.assertRaisesRegex(ValueError,'journal'):backend.recover()
            backend.durable_write.assert_not_called()
            self.assertTrue(marker.exists())


    def test_malformed_journal_never_restores_partial_state(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'gateway-activation.pending.json').write_text('pending')
            backend = Backend(SimpleNamespace(DEPLOY=base, STATE=base))
            paths = {base / str(i) for i in range(6)}
            backend.activation_paths = lambda: paths
            valid = [{'path':str(p),'uid':0,'gid':0,'mode':0o600,
                      'contents':base64.b64encode(b'original').decode()} for p in paths]
            backend.durable_write = Mock()
            for invalid in [None, {}, {'path':None}, {**valid[0],'contents':'!invalid!'},
                            {**valid[0],'uid':True}, {**valid[0],'mode':0o666}]:
                backend.read_json = lambda _, invalid=invalid: valid[1:]+[invalid]
                with self.assertRaises(ValueError):backend.recover()
                backend.durable_write.assert_not_called()


if __name__ == '__main__':
    unittest.main()
