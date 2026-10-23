#!/usr/bin/env python3
"""Fresh-install and benchmark safety boundaries; no host mutations."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def module(name):
    loader = importlib.machinery.SourceFileLoader(name.replace('-', '_'), str(ROOT / 'scripts/pricetag' / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    result = importlib.util.module_from_spec(spec)
    loader.exec_module(result)
    return result


installer = module('install.py')
benchmark = module('benchmark')


class InstallTest(unittest.TestCase):
    def test_credentials_fail_before_installation_commands(self):
        args = installer.parse_args(['--mode', 'real', '--hostname', 'gateway.example',
                                     '--provider', 'openai', '--openai-key-file', '/root/key', '--yes'])
        with patch.object(installer, 'preflight'), patch.object(installer, 'provider_module'), \
                patch.object(installer, 'collect_providers', side_effect=ValueError('HTTP 401')), \
                patch.object(installer, 'run', side_effect=AssertionError('installation must not start')):
            with self.assertRaisesRegex(ValueError, 'HTTP 401'):
                installer.install(args)

    def test_cancel_after_discovery_does_not_start_installation(self):
        args = installer.parse_args(['--mode', 'real', '--hostname', 'gateway.example',
                                     '--provider', 'openai', '--plan'])
        args.plan = False
        with patch.object(installer, 'preflight'), patch.object(installer, 'provider_module'), \
                patch.object(installer, 'collect_providers', return_value=[]), \
                patch('builtins.input', return_value='cancel'), \
                patch.object(installer, 'run', side_effect=AssertionError('installation must not start')):
            with self.assertRaisesRegex(ValueError, 'cancelled'):
                installer.install(args)

    def test_interactive_selection_accepts_menu_numbers(self):
        with patch.object(installer.sys.stdin, 'isatty', return_value=True), \
                patch('builtins.input', side_effect=['2', '2']):
            args = installer.parse_args(['--mode', 'real', '--hostname', 'gateway.example'])
        self.assertEqual(args.provider, ['external'])
        self.assertEqual(args.external_api, 'anthropic')

    def test_external_selection_requires_one_provider_and_records_api(self):
        with patch.object(installer.sys.stdin, 'isatty', return_value=False):
            with self.assertRaises(SystemExit):
                installer.parse_args(['--mode', 'real', '--hostname', 'gateway.example', '--yes'])
            args = installer.parse_args(['--mode', 'real', '--hostname', 'gateway.example',
                '--provider', 'external', '--external-api', 'anthropic', '--external-key-file', '/root/key',
                '--external-messages-url', 'provider.example', '--yes'])
            self.assertEqual(args.external_api, 'anthropic')
            self.assertEqual(args.provider, ['external'])

    def test_plan_runs_without_privileges_and_does_not_invoke_commands(self):
        with patch.object(sys, 'argv', ['install', '--mode', 'mock', '--hostname', 'gateway.example', '--plan']), \
                patch.object(installer, 'run', side_effect=AssertionError('mutation')), \
                patch.object(installer, 'preflight', side_effect=AssertionError('host inspection')):
            installer.main()

    def test_unattended_real_install_requires_credentials_and_endpoint(self):
        base = ['--mode', 'real', '--hostname', 'gateway.example', '--provider', 'pricetag', '--yes']
        with patch.object(installer.sys.stdin, 'isatty', return_value=False):
            with self.assertRaises(SystemExit):
                installer.parse_args(base)
            with self.assertRaises(SystemExit):
                installer.parse_args(base + ['--pricetag-key-file', '/root/key'])
            args = installer.parse_args(base + ['--pricetag-key-file', '/root/key',
                                               '--pricetag-messages-url', 'provider.example'])
            self.assertEqual(args.pricetag_key_file, Path('/root/key'))

    def test_existing_configuration_refused_without_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(installer.os, 'geteuid', return_value=0), \
                    patch.object(installer.Path, 'read_text', return_value='ID=rhel\n'), \
                    patch.object(installer, 'DEPLOY', Path(directory)), \
                    patch.object(installer, 'run', side_effect=AssertionError('mutation')):
                with self.assertRaisesRegex(ValueError, 'already exists'):
                    installer.preflight('real')

    def test_rejects_url_or_shell_input_as_hostname(self):
        for value in ('https://gateway.example', 'gateway.example:8443', 'a\nb', '-x', 'a/b', 'a;id', ''):
            self.assertFalse(installer.valid_hostname(value), value)
        for value in ('gateway.example', '127.0.0.1'):
            self.assertTrue(installer.valid_hostname(value))

    def test_checkout_commands_use_readable_source_permissions(self):
        from types import SimpleNamespace
        with patch.object(installer.subprocess, 'run', return_value=SimpleNamespace(stdout='')) as execute:
            installer.run(['git', 'clone', 'https://example.invalid/source', '/tmp/source'])
            self.assertEqual(execute.call_args.kwargs['umask'], 0o022)
            installer.run(['true'])
            self.assertEqual(execute.call_args.kwargs['umask'], -1)

    def test_import_looks_up_loaded_image_by_id_not_registry_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Path(directory) / 'podman'
            engine.write_text('#!/bin/sh\nexit 0\n')
            engine.chmod(0o755)
            import os
            for image_id in ('a' * 64, 'sha256:' + 'a' * 64):
                with patch.dict(os.environ, {'PATH': directory + ':' + os.environ['PATH']}), \
                        patch.object(installer, 'run', side_effect=[image_id, image_id]) as execute:
                    self.assertEqual(installer.import_image('registry/image@sha256:manifest', ['true']),
                                     'sha256:' + 'a' * 64)
                    self.assertIn(image_id, execute.call_args.args[0])

    def test_mock_rejects_provider_flags(self):
        with self.assertRaises(SystemExit):
            installer.parse_args(['--mode', 'mock', '--hostname', 'localhost', '--provider', 'openai'])

    def test_image_export_failure_does_not_prepare_or_inspect(self):
        # Real pipe behavior: exporter failure must survive an importer that exits 0.
        with tempfile.TemporaryDirectory() as directory:
            engine = Path(directory) / 'podman'
            engine.write_text('#!/bin/sh\nexit 7\n')
            engine.chmod(0o755)
            import os
            with patch.dict(os.environ, {'PATH': directory + ':' + os.environ['PATH']}), \
                    patch.object(installer, 'run', side_effect=['a' * 64]):
                with self.assertRaises(RuntimeError):
                    installer.import_image('unused', ['true'])

    def test_benchmark_rejects_real_models_and_provider_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'models.json').write_text('[{"id":"openai/real","model":"real"}]')
            with self.assertRaises(ValueError):
                benchmark.require_mock(path)
            (path / 'models.json').write_text('[{"id":"fixture","model":"fixture"}]')
            (path / 'quadlets').mkdir()
            (path / 'quadlets/pricetag-gateway.container').write_text(
                'Network=pricetag-mock.network\nSecret=real,type=env,target=KEY\n')
            with self.assertRaises(ValueError):
                benchmark.require_mock(path)

    def test_mock_guard_accepts_rendered_fixture_and_rejects_remote_endpoints(self):
        sys.path.insert(0, str(ROOT / 'scripts/pricetag'))
        import prepare
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            config, models = prepare.mock_inputs()
            (path / 'models.json').write_text(json.dumps(models))
            (path / 'quadlets').mkdir()
            (path / 'quadlets/pricetag-gateway.container').write_text(
                prepare.gateway_quadlet_body('sha256:' + 'a' * 64, [], '', True))
            (path / 'gateway').mkdir()
            rendered = prepare.render(config, models)
            (path / 'gateway/gateway.json').write_text(json.dumps(rendered))
            benchmark.require_mock(path)
            for chain in rendered['filter_chains']:
                for item in chain['filters']:
                    if item.get('filter') == 'load_balancer':
                        item['clusters'][0]['endpoints'] = ['remote.example:443']
            (path / 'gateway/gateway.json').write_text(json.dumps(rendered))
            with self.assertRaises(ValueError):
                benchmark.require_mock(path)

    def test_sampler_errors_and_disk_pressure_fail(self):
        with self.assertRaises(ValueError):
            benchmark.check_sample({'postgres': {'error': 'failed'}})
        with self.assertRaises(ValueError):
            benchmark.check_sample({'disk_available_percent': 29})

    def test_budget_only_rejects_key_rotation(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/pricetag/user'),
                                 '--subject', 'alice', '--no-key', '--rotate'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--no-key cannot', result.stderr)


if __name__ == '__main__':
    unittest.main()
