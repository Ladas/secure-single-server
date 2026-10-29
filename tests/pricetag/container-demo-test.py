#!/usr/bin/env python3
"""Check that disposable deployment diagnostics cannot publish raw credentials."""
import importlib.util
from pathlib import Path
import unittest

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


if __name__ == '__main__':
    unittest.main()
