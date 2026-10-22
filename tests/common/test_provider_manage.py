"""The provider transaction adopts a deployment with no manifest yet."""
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'scripts/common'), str(ROOT / 'tests/common')]
import provider_manage


class TransactionTest(unittest.TestCase):
    def test_adopts_a_deployment_without_a_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            changed = root / 'shared-gateway.yaml'
            changed.write_bytes(b'new config')
            manifest = root / 'shared-gateway.manifest'
            provider_manage.transaction({changed: b'new config'}, manifest, os.getgid(),
                                        activate=lambda: None)
            self.assertTrue(manifest.exists())
            expected = hashlib.sha256(b'new config').hexdigest() + '  ' + str(changed) + '\n'
            self.assertEqual(manifest.read_text(), expected)


if __name__ == '__main__':
    unittest.main()
