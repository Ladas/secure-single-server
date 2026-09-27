#!/usr/bin/env python3
"""Offline behavioral regressions for harness argument, policy and SSH contracts."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[2]

class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.td = Path(self.temp.name)
        self.log = self.td / 'calls'
        mock = self.td / 'openshell'
        mock.write_text('''#!/usr/bin/env python3
import json,os,pathlib,sys
a=sys.argv[1:]
with open(os.environ['MOCK_LOG'],'a') as f: f.write(json.dumps(a)+'\\n')
if a[:2]==['sandbox','list']:
 print(json.dumps({'sandboxes':[{'name':os.environ['MOCK_NAME'],'phase':'Ready'}]}))
if '--policy' in a:
 p=pathlib.Path(a[a.index('--policy')+1]).read_text()
 assert 'port: "8080"' not in p and '@@' not in p
''')
        mock.chmod(0o755)
        ssh = self.td / 'ssh'
        ssh.write_text('''#!/usr/bin/env python3
import json,os,sys
with open(os.environ['MOCK_LOG'],'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')
sys.stdin.read()
''')
        ssh.chmod(0o755)
        self.env = {**os.environ, 'PATH': str(self.td)+':'+os.environ['PATH'],
                    'OPENSHELL_BIN':str(mock), 'MOCK_LOG':str(self.log),
                    'OPENSHELL_MODEL_ID':'test-model', 'MOCK_NAME':'regression'}

    def create(self,h,*args):
        return subprocess.run(['bash',str(ROOT/'openshell/harnesses'/h/'create.sh'),
                               '--name','regression',*args], env=self.env,
                              input='', capture_output=True,text=True,timeout=10)

    def test_standalone_detached_and_explicit_provider(self):
        for h in ('codex','opencode','openclaw'):
            r=self.create(h,'--profile','dev','--provider','synthetic')
            self.assertEqual(r.returncode,0,r.stderr)
        calls=[json.loads(s) for s in self.log.read_text().splitlines()]
        for c in calls:
            if c[:2]==['sandbox','create']:
                self.assertIn('--detach',c)
                self.assertIn('--no-auto-providers',c)
                self.assertEqual(c[c.index('--provider')+1],'synthetic')

    def test_invalid_arguments_never_create(self):
        for h in ('codex','opencode','openclaw'):
            for args in (('--profile',),('--profile','../dev'),('--unknown','x'),('--config',),('--backend','anthropic')):
                r=self.create(h,*args)
                self.assertNotEqual(r.returncode,0)
                self.assertNotIn('unbound variable',r.stderr)
        self.assertFalse(self.log.exists())

    def test_integrated_contract(self):
        config=str(ROOT/'configs/openshell-praxis')
        for h in ('codex','openclaw'):
            self.assertNotEqual(self.create(h,'--profile','dev','--config',config).returncode,0)
        self.env['PRAXIS_PORT']='8080";bad'
        self.assertNotEqual(self.create('opencode','--profile','dev','--config',config).returncode,0)
        self.env['PRAXIS_PORT']='8080'
        self.assertNotEqual(self.create('opencode','--profile','dev','--config',config,'--provider','x').returncode,0)
        r=self.create('opencode','--profile','dev','--config',config)
        self.assertEqual(r.returncode,0,r.stderr)
        calls=[json.loads(s) for s in self.log.read_text().splitlines()]
        self.assertNotIn('--provider',calls[0])
        ssh=calls[-1]
        self.assertIn('/dev/null',ssh)
        self.assertFalse(any('SendEnv' in x or 'API_KEY' in x for x in ssh))

if __name__=='__main__': unittest.main()
