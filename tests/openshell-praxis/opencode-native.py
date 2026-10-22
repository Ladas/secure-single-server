#!/usr/bin/env python3
"""Pinned OpenCode/Praxis streamed tool and command contract, without OpenShell.

Actual OpenShell enforcement is covered separately on disposable RHEL runners.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
import yaml

ROOT = Path(__file__).resolve().parents[2]
ENGINE = os.environ.get('CONTAINER_ENGINE', 'podman')
spec = importlib.util.spec_from_file_location('opencode_fixture', Path(__file__).with_name('opencode-provider.py'))
fixture_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture_module)
fixture_module.provider.continuation = fixture_module.continuation
fixture_module.provider.completion = fixture_module.completion
sys.path.insert(0, str(ROOT / 'tests/common'))
from evidence import save


def run(*args):
    return subprocess.run(list(map(str, args)), text=True, capture_output=True, timeout=240)


def main():
    values = dict(line.split('=', 1) for line in (ROOT / 'openshell/configs/images.env').read_text().splitlines()
                  if line.startswith('ODH_'))
    image = json.loads(values['ODH_OPENCODE_IMAGE'])
    praxis = subprocess.check_output(['bash', '-c', 'source "$1/scripts/common/lib.sh"; printf %s "$DEFAULT_PRAXIS_IMAGE"',
                                      'test', str(ROOT)], text=True)
    evidence = {'status': 'failed', 'opencode_image': image, 'praxis_image': praxis,
                'openshell_runtime': 'not covered by this client/gateway test', 'cases': []}
    try:
        for pinned in (image, praxis):
            pulled = run(ENGINE, 'pull', pinned)
            if pulled.returncode:
                raise RuntimeError('Failed to pull pinned image: ' + pulled.stderr[-2000:])
        for local in (False, True):
            fixture = fixture_module.provider.Provider(ports=(18000, 0, 0), model='fixture-model', local=local)
            fixture.start()
            name = 'opencode-praxis-' + uuid.uuid4().hex[:10]
            try:
                with tempfile.TemporaryDirectory() as directory:
                    work = Path(directory); work.chmod(0o755)
                    home = work / 'home'; home.mkdir(); home.chmod(0o777)
                    sandbox = work / 'sandbox'; sandbox.mkdir(); sandbox.chmod(0o777)
                    configdir = home / '.config/opencode'; configdir.mkdir(parents=True)
                    template = ROOT / ('configs/vllm/harness' if local else 'configs/openshell-praxis') / 'harness-provider.json.in'
                    config = json.loads(template.read_text())
                    p = config['provider']['praxis']
                    p['options']['baseURL'] = 'http://127.0.0.1:18080/v1'
                    p['models'] = {'fixture-model': p['models']['@@MODEL_ID@@']}
                    config['model'] = 'praxis/fixture-model'
                    (configdir / 'opencode.json').write_text(json.dumps(config))
                    gateway = yaml.safe_load((ROOT / 'configs/vllm/praxis.yaml').read_text())
                    gateway['listeners'][0]['address'] = '127.0.0.1:18080'
                    filters = gateway['filter_chains'][0]['filters']
                    upstream = next(f for f in filters if f['filter'] == 'load_balancer')['clusters'][0]
                    upstream.update(endpoints=['127.0.0.1:18000'], http={'authority': 'localhost:18000'})
                    if not local:
                        filters.insert(-1, {'filter': 'credential_injection', 'clusters': [
                            {'name': 'openai', 'header': 'Authorization', 'header_prefix': 'Bearer ', 'env_var': 'OPENAI_API_KEY'}]})
                    gateway_path = work / 'praxis.yaml'; gateway_path.write_text(yaml.safe_dump(gateway))
                    started = run(ENGINE, 'run', '-d', '--name', name, '--network=host',
                                  '--read-only', '--cap-drop=all', '--security-opt=no-new-privileges',
                                  '--user=1001:1001', '-e', 'OPENAI_API_KEY=synthetic-openai',
                                  '-v', f'{gateway_path}:/etc/praxis/test.yaml:ro,Z', praxis, '-c', '/etc/praxis/test.yaml')
                    if started.returncode:
                        raise RuntimeError(started.stderr)
                    for attempt in range(30):
                        try:
                            urllib.request.urlopen('http://127.0.0.1:18080/v1/models', timeout=2).read()
                            break
                        except OSError:
                            if attempt == 29: raise
                            time.sleep(1)
                    args = [ENGINE, 'run', '--rm', '--network=host', '--user=1001:1001',
                            '--cap-drop=all', '--security-opt=no-new-privileges', '-e', 'HOME=/home/sandbox',
                            '-v', f'{home}:/home/sandbox:Z', '-v', f'{sandbox}:/sandbox:Z', '-w', '/sandbox',
                            '--entrypoint', '/usr/local/bin/opencode', image, 'run', '--format', 'json',
                            '--model', 'praxis/fixture-model', 'Write the proof script, run it with bash, then confirm completion.']
                    if Path(ENGINE).name == 'podman' and os.geteuid() != 0:
                        args.insert(3, '--userns=keep-id:uid=1001,gid=1001')
                    response = run(*args)
                    if response.returncode:
                        raise RuntimeError('OpenCode failed: ' + response.stderr[-2000:] + response.stdout[-2000:])
                    items = [json.loads(line) for line in response.stdout.splitlines() if line.startswith('{')]
                    if any(item.get('type') == 'error' for item in items) or not any(
                            item.get('type') == 'text' and fixture_module.MARKER in item.get('part', {}).get('text', '') for item in items):
                        raise RuntimeError('Missing successful final response: ' + response.stdout[-2000:])
                    if (sandbox / 'opencode-exec-proof.txt').read_text().strip() != fixture_module.MARKER:
                        raise RuntimeError('Independent command-produced file contents do not match')
                    records = list(fixture.records)
                    if not any(r.get('continuation') for r in records) or not all(r['credential_ok'] for r in records):
                        raise RuntimeError('Tool continuation or upstream credential contract failed')
                    evidence['cases'].append({'upstream': 'credentialless' if local else 'bearer-authenticated',
                                              'status': 'passed', 'records': records})
                    print('PASS OpenCode streamed its bash tool, continuation, and credentials:', evidence['cases'][-1]['upstream'])
            finally:
                fixture.close()
                run(ENGINE, 'rm', '-f', name)
        evidence['status'] = 'passed'
    finally:
        save('opencode-native', evidence)


if __name__ == '__main__':
    main()
