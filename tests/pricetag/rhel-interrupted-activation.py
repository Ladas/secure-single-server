#!/usr/bin/env python3
"""Kill a mock activation after its first write; verify daemon-start recovery.

Run only on an idle benchmark. The fault exists only in the child test process;
it is never installed in production code or the systemd unit.
"""
import copy
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
INSTALLED = Path('/opt/praxis-gateway-management')
DEPLOY = Path('/etc/praxis-pricetag')


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def main():
    if os.geteuid() != 0:
        raise ValueError('run as root on the idle mock benchmark')
    load('benchmark', ROOT / 'scripts/pricetag/benchmark').require_mock(DEPLOY)
    sys.path[:0] = [str(INSTALLED / 'scripts/pricetag'), str(INSTALLED / 'scripts/common')]
    from gateway_management_backend import Backend
    from gateway_management import validate
    helpers = load('provider_helpers', INSTALLED / 'scripts/pricetag/providers')
    backend = Backend(helpers)
    pending = DEPLOY / 'gateway-activation.pending.json'
    if pending.exists() or pending.is_symlink():
        raise ValueError('finish existing recovery before this test')
    originals = {path: path.read_bytes() for path in backend.activation_paths()}
    document = copy.deepcopy(backend.read())
    document['models'][0]['output'] -= 1
    policy = backend.read_json('gateway-management-policy.json')
    assert policy == {'approved_origins': ['http://pricetag-provider:18080', 'http://pricetag-provider:18081'], 'mock': True}
    validate(document, policy['approved_origins'])
    unit = 'praxis-gateway-management.service'
    subprocess.run(['systemctl', 'stop', unit], check=True)
    try:
        child = os.fork()
        if child == 0:
            try:
                def interrupted(files, **kwargs):
                    target = DEPLOY / 'gateway/gateway.json'
                    info = target.stat()
                    backend.durable_write(target, files[target], info.st_uid, info.st_gid, info.st_mode & 0o777)
                    os._exit(73)
                helpers.install_replacement = interrupted
                with backend.lock():
                    backend.activate(document, {})
            finally:
                os._exit(74)
        _, result = os.waitpid(child, 0)
        assert os.waitstatus_to_exitcode(result) == 73, 'fault did not reach the intended write'
        assert pending.is_file(), 'no durable rollback journal'
        assert (DEPLOY / 'gateway/gateway.json').read_bytes() != originals[DEPLOY / 'gateway/gateway.json']
        subprocess.run(['systemctl', 'start', unit], check=True)
        for _ in range(90):
            if not pending.exists():
                break
            time.sleep(1)
        assert not pending.exists(), 'recovery did not complete'
        for path, content in originals.items():
            assert path.read_bytes() == content, 'recovery did not restore every file'
        subprocess.run(['systemctl', 'is-active', unit], check=True)
        tls = ssl.create_default_context(cafile=str(DEPLOY / 'ca.pem'))
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=tls))
        key = Path('/root/pricetag-admin/admin.key').read_text().strip()
        model = json.loads(originals[DEPLOY / 'models.json'])[0]['id']
        request = urllib.request.Request('https://localhost:8443/v1/chat/completions',
            json.dumps({'model': model, 'messages': [{'role':'user','content':'synthetic recovery verification'}], 'max_completion_tokens':16}).encode(),
            headers={'Content-Type':'application/json', 'Authorization':'Bearer '+key})
        with opener.open(request, timeout=30) as response:
            assert response.status == 200
            response.read()
        print('PASS: interrupted first write recovered all six files on adapter start; verified-TLS inference works')
    finally:
        # If a test assertion fails, leave recovery available and retain its
        # journal rather than deleting the only durable restoration record.
        subprocess.run(['systemctl', 'start', unit], check=True)


if __name__ == '__main__':
    main()
