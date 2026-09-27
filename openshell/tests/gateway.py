#!/usr/bin/env python3
"""Check shared gateway behavior without changing host services or ownership."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.td = Path(self.temp.name)
        (self.td / 'home/.config/openshell').mkdir(parents=True)
        (self.td / 'units').mkdir()
        self.env = {**os.environ, 'TEST_ROOT': str(ROOT), 'TEST_TMP': str(self.td)}

    def run_shell(self, body):
        return subprocess.run(['bash', '-c', '''
set -euo pipefail
source "$TEST_ROOT/openshell/scripts/lib.sh"
source "$TEST_ROOT/openshell/scripts/gateway-lib.sh"
''' + body], env=self.env, capture_output=True, text=True)

    def test_config_preserves_workload_and_startup_contracts(self):
        for autostart in ('yes', 'no'):
            self.env['AUTOSTART'] = autostart
            result = self.run_shell('''
id() { if [[ "$1" == -u ]]; then echo 1234; else echo owner; fi; }
install() {
  printf '%s\n' "$*" >>"$TEST_TMP/install.log"
  local src="${@: -2:1}" dst="${@: -1}"
  [[ "$dst" != /etc/* ]] || dst="$TEST_TMP/units/${dst##*/}"
  cp "$src" "$dst"
}
gateway_install_config owner "$TEST_TMP/home" "$TEST_TMP" 'example/harness@sha256:abc' "$AUTOSTART"
''')
            self.assertEqual(result.returncode, 0, result.stderr)
            config = (self.td / 'home/.config/openshell/gateway.toml').read_text()
            unit = (self.td / 'units/openshell-gateway.container').read_text()
            self.assertIn('default_image     = "example/harness@sha256:abc"', config)
            self.assertNotIn('@@', config + unit)
            self.assertEqual('[Install]' in unit, autostart == 'yes')
            self.assertIn('Exec=--bind-address 127.0.0.1 --port 8090', unit)
            self.assertIn('PodmanArgs=--userns=keep-id:uid=1001,gid=1001', unit)
            calls = (self.td / 'install.log').read_text()
            self.assertIn('-m 0600', calls)
            self.assertIn('-m 0644', calls)

    def test_restart_retains_cli_registration(self):
        result = self.run_shell('''
runner() { printf '%s\n' "$*" >>"$TEST_TMP/calls"; [[ "$1" != touch ]] || touch "$2"; }
curl() { return 0; }
gateway_start runner /native/openshell "$TEST_TMP/registered"
gateway_start runner /native/openshell "$TEST_TMP/registered"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = (self.td / 'calls').read_text()
        self.assertEqual(calls.count('gateway add'), 1)
        self.assertEqual(calls.count('gateway select'), 1)
        self.assertEqual(calls.count('sandbox list'), 2)
        self.assertEqual(calls.count('restart openshell-gateway.service'), 2)

    def test_failed_health_does_not_register_cli(self):
        result = self.run_shell('''
runner() { printf '%s\n' "$*" >>"$TEST_TMP/calls"; }
curl() { return 22; }
sleep() { :; }
gateway_start runner /native/openshell "$TEST_TMP/registered"
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('gateway add', (self.td / 'calls').read_text())
        self.assertFalse((self.td / 'registered').exists())

if __name__ == '__main__':
    unittest.main()
