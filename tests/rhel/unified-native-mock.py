#!/usr/bin/env python3
"""Qualify installed RHEL CLIs through a local isolated mock gateway over SSH."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'scripts/common'), str(ROOT / 'tests/common')]
import harness_config
from unified_config import catalog

spec = importlib.util.spec_from_file_location('unified_image', Path(__file__).with_name('unified-image.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True, help='admin SSH login, e.g. ec2-user@HOST')
    parser.add_argument('--ssh-key', type=Path, required=True)
    parser.add_argument('--user', required=True, help='existing ordinary harness user on RHEL')
    parser.add_argument('--deployment-dir', default='/home/ec2-user/secure-single-server-deploy',
                        help='absolute path to the matching deployment checkout on RHEL')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,30}', args.user) or args.host.startswith('-'):
        parser.error('invalid user or SSH host')
    if not Path(args.deployment_dir).is_absolute():
        parser.error('--deployment-dir must be absolute')
    ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'ForwardAgent=no',
           '-o', 'ExitOnForwardFailure=yes', '-i', str(args.ssh_key)]
    fixture.UnifiedGateway.harnesses = True
    with fixture.UnifiedGateway('all-in-one', 'valkey') as gateway:
        forward = subprocess.Popen([*ssh, '-N', '-R', '127.0.0.1:18080:127.0.0.1:' + gateway.openai_port,
                                    '-R', '127.0.0.1:18081:127.0.0.1:' + gateway.anthropic_port, args.host],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        try:
            time.sleep(1)
            if forward.poll() is not None:
                raise RuntimeError('SSH loopback forwarding failed: ' + forward.stderr.read())
            home = Path('/home') / args.user / 'rhel-smoke' / ('unified-mock-config-' + uuid.uuid4().hex[:8])
            outputs = harness_config.files(home,
                catalog([m for m in fixture.MODELS if 'openai' in m['apis']], 'openai')['data'],
                catalog([m for m in fixture.MODELS if 'anthropic' in m['apis']], 'anthropic')['data'], 18080, 18081)
            remote = '''import importlib.util,json,os,pwd,sys
from pathlib import Path
sys.path.insert(0,str(Path(DEPLOYMENT)/"tests/rhel"))
spec=importlib.util.spec_from_file_location("native",Path(sys.path[0])/"unified-native.py")
native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
native.integration.USER=USER
account=pwd.getpwnam(USER)
root=Path(CONFIG_ROOT)
root.mkdir(parents=True,mode=0o700)
os.chown(root,account.pw_uid,account.pw_gid)
for filename,content in OUTPUTS.items():
 p=Path(filename);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content);p.chmod(0o600)
for p in root.rglob("*"):os.chown(p,account.pw_uid,account.pw_gid)
env={"CODEX_HOME":str(root/".codex"),"CLAUDE_CONFIG_DIR":str(root/".claude"),
     "OPENCODE_CONFIG":str(root/".config/opencode/opencode.json")}
failures=[]
for model in MODELS:
 for api in model["apis"]:
  for name in (["claude","opencode"] if api=="anthropic" else ["codex","opencode"]):
   print("RUN mock "+name+": "+model["id"]+" ("+api+")",flush=True)
   try:native.qualify(name,model["id"],env,api)
   except Exception as e:failures.append(str(e));print("FAIL "+str(e),flush=True)
if failures:raise SystemExit(1)
'''
            parameters = {'USER': args.user, 'CONFIG_ROOT': str(home), 'DEPLOYMENT': args.deployment_dir,
                          'OUTPUTS': {str(k): v for k, v in outputs.items()}, 'MODELS': fixture.MODELS}
            code = 'import json\nglobals().update(json.loads(' + repr(json.dumps(parameters)) + '))\n' + remote
            result = subprocess.run([*ssh, args.host, 'sudo python3 -'], input=code, text=True, check=False)
            if result.returncode:
                raise RuntimeError('native mock tasks failed')
            # Each upstream must see its actual model, correct server-held key,
            # streaming and a completed tool-result continuation.
            for port in (19001, 19002, 19003):
                records = json.loads(fixture.run(fixture.ENGINE, 'exec', gateway.name + '-mock', 'python3', '-c',
                    'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:' + str(port) +
                    '/state").read().decode())'))['records']
                assert records and all(r['credential_ok'] for r in records), ('credentials', port)
                assert any(r['continuation'] for r in records) and any(r['stream'] for r in records), ('tools', port)
                if port in (19002, 19003):
                    gpt = [r for r in records if r['model'].startswith('gpt-')]
                    assert gpt and all(r['path'] == '/v1/responses' for r in gpt), ('GPT must use Responses', port)
                assert not any(r['path'] == '/v1/chat/completions' for r in records), 'native tests use Responses/Messages'
            print('PASS: mock vLLM, direct cloud and multi-API custom provider with native RHEL harnesses', flush=True)
        finally:
            forward.terminate()
            forward.wait(timeout=10)


if __name__ == '__main__':
    main()
