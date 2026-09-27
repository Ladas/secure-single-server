#!/usr/bin/env python3
"""Exercise build argument validation and context isolation without a registry."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PIN = 'registry.redhat.io/rhel9/rhel-bootc@sha256:' + 'a' * 64


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.log = self.directory / 'calls'
        podman = self.directory / 'podman'
        podman.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ['CALL_LOG'], 'a') as output:
    output.write(json.dumps(args) + '\\n')
if args[0] == 'info':
    print(os.environ.get('TEST_PLATFORM', 'linux/amd64'))
elif args[:2] == ['image', 'inspect']:
    print('b' * 64)
elif args[0] == 'build':
    context = pathlib.Path(args[-1])
    assert not (context / '.git').exists()
    assert not (context / '.state').exists()
    assert not (context / 'evidence').exists()
    assert (context / 'openshell/configs/images.env').is_file()
    assert (context / 'bootc/scripts/reconcile').is_file()
else:
    sys.exit(3)
''')
        podman.chmod(0o755)
        self.env = {**os.environ, 'PATH': str(self.directory) + ':' + os.environ['PATH'],
                    'CALL_LOG': str(self.log), 'RHEL_BOOTC_IMAGE': PIN}

    def run_build(self, *args):
        return subprocess.run([str(ROOT / 'bootc/build'), *args], env=self.env,
                              capture_output=True, text=True)

    def test_all_derivatives_use_same_resolved_parent(self):
        import json
        result = self.run_build('all')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(row) for row in self.log.read_text().splitlines()]
        builds = [call for call in calls if call[0] == 'build']
        self.assertEqual(len(builds), 4)
        self.assertIn('RHEL_BOOTC_IMAGE=' + PIN, builds[0])
        for harness, call in zip(('codex', 'opencode', 'openclaw'), builds[1:]):
            self.assertIn('BASE_IMAGE=' + 'b' * 64, call)
            self.assertIn('HARNESS=' + harness, call)
            self.assertIn('--pull=never', call)

    def test_rejects_unpinned_or_wrong_distribution(self):
        for image in ('registry.redhat.io/rhel9/rhel-bootc:latest',
                      'registry.redhat.io/rhel10/rhel-bootc@sha256:' + 'a' * 64):
            self.env['RHEL_BOOTC_IMAGE'] = image
            self.assertNotEqual(self.run_build('base').returncode, 0)
        self.assertNotIn('"build"', self.log.read_text())

    def test_rejects_arm_builder(self):
        self.env['TEST_PLATFORM'] = 'linux/arm64'
        self.assertNotEqual(self.run_build('base').returncode, 0)
        self.assertNotIn('"build"', self.log.read_text())

    def test_rejects_path_traversal_before_podman(self):
        self.assertNotEqual(self.run_build('../codex').returncode, 0)
        self.assertFalse(self.log.exists())


class HarnessScriptTests(unittest.TestCase):
    def test_profile_validation_after_loading_shared_libraries(self):
        # Regression: CONFIG_DIR collided with a readonly variable in the Praxis library.
        for harness in ('codex', 'opencode', 'openclaw'):
            with self.subTest(harness=harness):
                result = subprocess.run(
                    ['bash', str(ROOT / 'openshell/harnesses' / harness / 'create.sh'),
                     '--profile', 'invalid'], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('no such profile: invalid', result.stderr)
                self.assertNotIn('readonly variable', result.stderr)


if __name__ == '__main__':
    unittest.main()
