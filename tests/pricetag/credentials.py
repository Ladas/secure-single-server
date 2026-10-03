#!/usr/bin/env python3
"""Manual registry and non-expiring JWT lifecycle without a running gateway."""
import base64
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CredentialsTest(unittest.TestCase):
    def test_issue_rotate_revoke_and_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            subprocess.run([str(ROOT / 'scripts/remote-gateway/credentials'), 'init-jwt',
                '--directory', str(path / 'issuer')], check=True, capture_output=True)
            registry = path / 'users.json'

            def run(action, *extra):
                return subprocess.run([str(ROOT / 'scripts/pricetag/credentials'), action,
                    '--registry', str(registry), '--key', str(path / 'issuer/private.pem'), *extra],
                    capture_output=True, text=True)

            self.assertEqual(run('init').returncode, 0)
            first, second = path / 'first.jwt', path / 'second.jwt'
            self.assertEqual(run('issue', '--subject', 'alice', '--output', str(first)).returncode, 0)
            claims = json.loads(base64.urlsafe_b64decode(first.read_text().split('.')[1] + '==='))
            self.assertNotIn('exp', claims)
            self.assertEqual(claims['sub'], 'alice')
            self.assertEqual(first.stat().st_mode & 0o777, 0o600)
            original = json.loads(registry.read_text())['users']['alice']['digest']
            self.assertNotEqual(run('issue', '--subject', 'alice', '--output', str(second)).returncode, 0)
            self.assertFalse(second.exists())
            registry.chmod(0o640)
            rotated = run('rotate', '--subject', 'alice', '--output', str(second))
            self.assertEqual(rotated.returncode, 0, rotated.stderr)
            self.assertNotEqual(json.loads(registry.read_text())['users']['alice']['digest'], original)
            self.assertEqual(registry.stat().st_mode & 0o777, 0o640)
            self.assertEqual(run('revoke', '--subject', 'alice').returncode, 0)
            self.assertFalse(json.loads(registry.read_text())['users']['alice']['active'])
            self.assertIn('alice: revoked', run('list').stdout)
            self.assertNotIn(second.read_text().strip(), rotated.stdout)
            previous = registry.read_text()
            self.assertNotEqual(run('rotate', '--subject', 'alice', '--output', str(second)).returncode, 0)
            self.assertEqual(registry.read_text(), previous)
            registry.write_text('broken')
            self.assertNotEqual(run('revoke', '--subject', 'alice').returncode, 0)
            self.assertEqual(registry.read_text(), 'broken')


if __name__ == '__main__':
    unittest.main()
