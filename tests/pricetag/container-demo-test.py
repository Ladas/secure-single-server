#!/usr/bin/env python3
"""Check that disposable deployment diagnostics cannot publish raw credentials."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import subprocess
import json

spec = importlib.util.spec_from_file_location('container_demo', Path(__file__).with_name('container-demo.py'))
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class DiagnosticTests(unittest.TestCase):
    def test_known_failures_emit_only_fixed_codes(self):
        for message, expected in (
                ('No space left on device', 'database-storage-full'),
                ('Permission denied', 'database-permission-denied'),
                ('Out of memory', 'database-out-of-memory')):
            with self.subTest(message=message):
                diagnostic = f'password=do-not-publish\nFATAL: {message}\npostgres://secret@db'
                self.assertEqual(demo.database_failure_reason(diagnostic), expected)

    def test_unrecognized_failure_does_not_echo_logs(self):
        self.assertEqual(demo.database_failure_reason('secret-key-value'),
                         'database-bootstrap-failed')
        self.assertEqual(demo.database_failure_reason(''), 'database-bootstrap-failed')


class ReadinessTests(unittest.TestCase):
    def test_stopped_database_preserves_probe_error(self):
        error = subprocess.CalledProcessError(1, ['podman'], stderr='private diagnostic')
        with patch.object(demo, 'podman', side_effect=[error, 'false']), \
                patch.object(demo.time, 'sleep') as sleep:
            with self.assertRaises(subprocess.CalledProcessError) as caught:
                demo.wait_database('isolated-db')
        self.assertIs(caught.exception, error)
        sleep.assert_not_called()

    def test_running_database_retries_until_tcp_ready(self):
        error = subprocess.CalledProcessError(1, ['podman'])
        with patch.object(demo, 'podman', side_effect=[error, 'true', '1']) as command, \
                patch.object(demo.time, 'sleep'):
            demo.wait_database('isolated-db')
        probe = command.call_args.args
        self.assertIn('-h 127.0.0.1', probe[-1])
        self.assertIn('PGPASSWORD="$POSTGRES_PASSWORD"', probe[-1])

    def test_timeout_preserves_probe_error(self):
        error = subprocess.CalledProcessError(1, ['podman'], stderr='Connection refused')
        with patch.object(demo, 'podman', side_effect=[error, 'true']), \
                patch.object(demo.time, 'sleep'):
            with self.assertRaises(subprocess.CalledProcessError):
                demo.wait_database('isolated-db', attempts=1)

    def test_public_state_excludes_arbitrary_inspect_fields(self):
        data = [{'State': {'Running': False, 'ExitCode': 1, 'OOMKilled': False,
                           'Error': 'secret-value', 'Pid': 123}}]
        with patch.object(demo, 'podman', return_value=json.dumps(data)):
            self.assertEqual(demo.database_state('isolated-db'),
                             {'Running': False, 'ExitCode': 1, 'OOMKilled': False})


if __name__ == '__main__':
    unittest.main()
