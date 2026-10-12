#!/usr/bin/env python3
"""Offline cleanup regressions: never certify a failed or incomplete listing."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CleanupTests(unittest.TestCase):
    def run_case(self, mode, timeout='3', primary_status=None):
        with tempfile.TemporaryDirectory() as directory:
            td = Path(directory)
            mock = td / 'openshell'
            mock.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys, time
mode=os.environ['MODE']; td=pathlib.Path(os.environ['TD']); args=sys.argv[1:]
with (td/'calls').open('a') as f: f.write(json.dumps(args)+'\\n')
if mode=='hang': time.sleep(10)
if args[1]=='delete':
 if mode=='delete-error': sys.exit(7)
 (td/'deleted').touch(); sys.exit(0)
if mode=='list-error' or (mode=='poll-error' and (td/'deleted').exists()): sys.exit(9)
if mode=='incomplete': print(json.dumps({'sandboxes':[]})); sys.exit(0)
if mode=='bad-json': print('{}'); sys.exit(0)
if mode=='malformed': print('{'); sys.exit(0)
page=args[args.index('--page-token')+1]
if mode=='loop': print(json.dumps({'sandboxes':[], 'next_page_token':'again'})); sys.exit(0)
if mode=='pagination' and not page:
 print(json.dumps({'sandboxes':[{'name':'other'}], 'next_page_token':'next'})); sys.exit(0)
exists=mode!='absent' and (not (td/'deleted').exists() or mode=='stuck')
if mode=='async' and (td/'deleted').exists() and not (td/'polled').exists():
 (td/'polled').touch(); exists=True
print(json.dumps({'sandboxes':[{'name':'target'}] if exists else [], 'next_page_token':''}))
''')
            mock.chmod(0o755)
            env = {**os.environ, 'MODE': mode, 'TD': directory,
                   'OPENSHELL_CLEANUP_TIMEOUT': timeout, 'OPENSHELL_BIN': str(mock)}
            body = 'source "$1/openshell/scripts/harness-lib.sh"; harness_destroy "$2"'
            if primary_status is not None:
                body = '''source "$1/openshell/scripts/harness-lib.sh"
trap 'status=$?; if ! harness_destroy "$2" && (( status == 0 )); then status=1; fi; exit "$status"' EXIT
exit "$3"
'''
            result = subprocess.run(['bash', '-c', body,
                                     'cleanup-test', str(ROOT), 'target', str(primary_status)], env=env, capture_output=True,
                                    text=True, timeout=6)
            calls = [json.loads(line) for line in (td/'calls').read_text().splitlines()] if (td/'calls').exists() else []
            return result, calls

    def test_async_acceptance_waits_for_absence(self):
        result, calls = self.run_case('async')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sum(c[1]=='list' for c in calls), 3)

    def test_target_on_later_page_is_deleted(self):
        result, calls = self.run_case('pagination')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(['sandbox', 'delete', 'target'], calls)
        self.assertEqual(sum(c[-1]=='next' for c in calls), 2)

    def test_absent_is_idempotent(self):
        result, calls = self.run_case('absent')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(c[1]=='delete' for c in calls))

    def test_failures_never_certify_cleanup(self):
        for mode in ('delete-error', 'list-error', 'poll-error', 'bad-json', 'incomplete', 'malformed', 'loop'):
            with self.subTest(mode=mode):
                result, _ = self.run_case(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('cleanup failed', result.stderr)

    def test_deadline_bounds_stuck_sandbox_and_hung_cli(self):
        for mode in ('stuck', 'hang'):
            with self.subTest(mode=mode):
                result, _ = self.run_case(mode, '0.2')
                self.assertNotEqual(result.returncode, 0)

    def test_invalid_deadlines(self):
        for timeout in ('0', '-1', 'nan', 'inf', 'invalid'):
            with self.subTest(timeout=timeout):
                result, calls = self.run_case('absent', timeout)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, [])

    def test_exit_trap_reports_cleanup_failure_and_preserves_primary_failure(self):
        for mode, primary, expected in [('absent', 0, 0), ('list-error', 0, 1), ('absent', 7, 7), ('list-error', 7, 7)]:
            with self.subTest(mode=mode, primary=primary):
                result, _ = self.run_case(mode, primary_status=primary)
                self.assertEqual(result.returncode, expected, result.stderr)


if __name__ == '__main__':
    unittest.main()
