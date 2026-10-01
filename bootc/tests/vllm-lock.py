#!/usr/bin/env python3
"""Exercise the real dispatcher under pull contention without systemd or root."""
import fcntl
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which('flock'), 'util-linux flock is required')
class LockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.lock = (self.work / 'secure-single-server-vllm.lock').open('w')
        self.addCleanup(self.lock.close)
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        source = (ROOT / 'bootc/scripts/vllm').read_text()
        source = source.replace('source /usr/share/secure-single-server/bootc/scripts/common', ':')
        source = source.replace('source /usr/share/secure-single-server/bootc/scripts/vllm-common', ':')
        source = source.replace('source "${ROOT}/bootc/scripts/vllm-lib"', ':')
        source = source.replace('/run/', str(self.work) + '/')
        source = source.replace('/etc/secure-single-server', str(self.work / 'state'))
        # Dependencies are mocked; dispatch, locking, atomic selection and ordering are real.
        prelude = '''
require_root() { :; }
vllm_mode() { echo cpu; }
vllm_preflight() { [[ "$1" == disabled || "$1" == cpu || "$1" == gpu ]]; }
getent() { return "${NO_ACCOUNT:-0}"; }
as_service() { echo SERVICE_STATUS; }
note() { echo "$*"; }
die() { echo "$*" >&2; exit 1; }
systemctl() {
  if [[ "$1" == stop ]]; then
    touch "$WORK/stop-requested"
    while [[ ! -f "$WORK/pull-cancelled" ]]; do sleep 0.02; done
  else
    if [[ "$(cat "$WORK/state/vllm-mode")" != disabled && "$*" != *--no-block* ]]; then
      echo 'start must not hold the selector lock during preparation' >&2
      return 1
    fi
    # A restarted reconcile must be able to acquire the released lock.
    flock -n "$WORK/secure-single-server-vllm.lock" cat "$WORK/state/vllm-mode"
  fi
}
'''
        self.script = self.work / 'vllm'
        self.script.write_text(prelude + source)
        self.env = {**os.environ, 'WORK': str(self.work)}

    def test_status_does_not_wait_for_pull(self):
        result = subprocess.run(['bash', self.script, 'status'], env=self.env,
                                capture_output=True, text=True, timeout=2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('SERVICE_STATUS', result.stdout)

    def test_status_before_account_creation(self):
        result = subprocess.run(['bash', self.script, 'status'],
                                env={**self.env, 'NO_ACCOUNT': '1'},
                                capture_output=True, text=True, timeout=2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('not prepared yet', result.stdout)

    def test_disable_cancels_pull_before_waiting_for_reconcile_lock(self):
        import time
        process = subprocess.Popen(['bash', self.script, 'select', 'disabled'],
                                   env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 2
            while not (self.work / 'stop-requested').exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue((self.work / 'stop-requested').exists(),
                            'selector waited for the pull lock before cancelling the service')
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            (self.work / 'pull-cancelled').touch()
            stdout, stderr = process.communicate(timeout=2)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(stdout.strip(), 'disabled')
        finally:
            if process.poll() is None:
                (self.work / 'pull-cancelled').touch()
                process.kill()
            process.communicate()

    def test_enabled_selection_queues_preparation_without_holding_selector_lock(self):
        fcntl.flock(self.lock, fcntl.LOCK_UN)
        (self.work / 'pull-cancelled').touch()
        result = subprocess.run(['bash', self.script, 'select', 'cpu'], env=self.env,
                                capture_output=True, text=True, timeout=2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('preparation queued', result.stdout)

    def test_invalid_selection_does_not_stop_service(self):
        result = subprocess.run(['bash', self.script, 'select', 'invalid'], env=self.env,
                                capture_output=True, text=True, timeout=2)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.work / 'stop-requested').exists())


if __name__ == '__main__':
    unittest.main()
