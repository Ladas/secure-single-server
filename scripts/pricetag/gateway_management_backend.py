"""Host-owned file/Podman backend for gateway management.

Only the configuration compiler selects paths and commands. Keep this module and
its imported provider helpers root-owned when installing the daemon.
"""
from contextlib import contextmanager
import base64
import fcntl
import json
import os
from pathlib import Path
import pwd
import re
import stat
import tempfile

from gateway_management import merge_gateway


class Backend:
    def __init__(self, providers):
        self.providers = providers
        self.deploy = providers.DEPLOY
        self.state = providers.STATE

    @contextmanager
    def lock(self):
        self.providers.check_host(allow_active=True)
        descriptor = os.open(self.state / '.setup.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.recover()
            yield
        finally:
            os.close(descriptor)

    def read_json(self, name):
        path = self.deploy / name
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('configuration must be a root-owned regular file')
        return json.loads(path.read_text())

    def read(self):
        return self.read_json('gateway-management.json')

    def activation_paths(self):
        uid = pwd.getpwnam('praxis-svc').pw_uid
        return {self.deploy / name for name in ('gateway-management.json',
            'provider-secret-refs.json', 'gateway/gateway.json', 'models.json',
            'quadlets/pricetag-gateway.container')} | {
                self.providers.USER_UNITS / str(uid) / 'pricetag-gateway.container'}

    @staticmethod
    def durable_write(path, contents, uid, gid, mode):
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.activation-', delete=False) as output:
            temporary = Path(output.name)
            try:
                output.write(contents)
                output.flush()
                os.fchown(output.fileno(), uid, gid)
                os.fchmod(output.fileno(), mode)
                os.fsync(output.fileno())
                os.replace(temporary, path)
                descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            finally:
                temporary.unlink(missing_ok=True)

    def clear_journal(self):
        (self.deploy / 'gateway-activation.pending.json').unlink()
        descriptor = os.open(self.deploy, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def journal(self, files):
        if set(files) != self.activation_paths():
            raise ValueError('unexpected activation targets')
        entries = []
        for path in sorted(files):
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise ValueError('activation targets must be protected root-owned files')
            entries.append({'path': str(path), 'uid': info.st_uid, 'gid': info.st_gid,
                'mode': info.st_mode & 0o777, 'contents': base64.b64encode(path.read_bytes()).decode()})
        self.durable_write(self.deploy / 'gateway-activation.pending.json',
            (json.dumps(entries) + '\n').encode(), 0, 0, 0o600)

    def recover(self):
        path = self.deploy / 'gateway-activation.pending.json'
        if not path.exists() and not path.is_symlink():
            return
        entries = self.read_json('gateway-activation.pending.json')
        if not isinstance(entries, list) or len(entries) != 6:
            raise ValueError('invalid activation recovery journal')
        # Validate every entry before restoring any file. Journal contents are
        # root-owned configuration and secret references, never provider keys.
        restored = []
        for row in entries:
            if (not isinstance(row, dict) or set(row) != {'path', 'uid', 'gid', 'mode', 'contents'} or
                    not isinstance(row['path'], str) or not isinstance(row['contents'], str) or
                    type(row['uid']) is not int or row['uid'] != 0 or type(row['gid']) is not int or row['gid'] < 0 or
                    type(row['mode']) is not int or row['mode'] & ~0o755 or row['mode'] & 0o022):
                raise ValueError('invalid recovery metadata')
            restored.append((Path(row['path']), base64.b64decode(row['contents'], validate=True), row))
        if {target for target, _, _ in restored} != self.activation_paths():
            raise ValueError('invalid activation recovery journal targets')
        for target, contents, row in restored:
            self.durable_write(target, contents, row['uid'], row['gid'], row['mode'])
        self.providers.relabel([target for target, _, _ in restored])
        self.providers.activate_gateway()
        self.clear_journal()

    def activate(self, document, credentials):
        refs = self.read_json('provider-secret-refs.json')
        names = {p['name'] for p in document['providers']}
        if names - set(refs) - set(credentials):
            raise ValueError('new providers require credentials')
        # New versioned secrets are retained even after failed activation. A
        # partially failed rollback must never lose a credential it still uses.
        # Values go only to Podman stdin, never argv, logs or configuration JSON.
        for name, value in credentials.items():
            secret = self.providers.next_secret(name)
            result = self.providers.service('podman', 'secret', 'create', secret, '-',
                                            input=value.encode())
            if result.returncode:
                raise ValueError('provider secret creation failed')
            refs[name] = secret
        refs = {name: refs[name] for name in names}
        gateway = merge_gateway(self.read_json('gateway/gateway.json'), document)
        encoded = lambda value: (json.dumps(value, indent=2) + '\n').encode()
        files = {self.deploy / 'gateway-management.json': encoded(document),
                 self.deploy / 'provider-secret-refs.json': encoded(refs),
                 self.deploy / 'gateway/gateway.json': encoded(gateway),
                 self.deploy / 'models.json': encoded(document['models'])}
        uid = pwd.getpwnam('praxis-svc').pw_uid
        unit_paths = [self.deploy / 'quadlets/pricetag-gateway.container',
                      self.providers.USER_UNITS / str(uid) / 'pricetag-gateway.container']
        for path in unit_paths:
            lines = path.read_text().splitlines()
            lines = [line for line in lines if not re.fullmatch(
                r'Secret=[A-Za-z0-9_.-]+,type=env,target=[A-Z0-9_]+_API_KEY', line)]
            if lines.count('[Container]') != 1:
                raise ValueError('unexpected gateway unit')
            entries = []
            for name in sorted(names):
                target = 'OPENAI_API_KEY' if name == 'openai' else 'CUSTOM_' + name.upper().replace('-', '_') + '_API_KEY'
                entries.append(f'Secret={refs[name]},type=env,target={target}')
            index = lines.index('[Container]') + 1
            lines[index:index] = entries
            files[path] = ('\n'.join(lines) + '\n').encode()
        self.journal(files)
        try:
            self.providers.install_replacement(files)
        except Exception:
            # Complete durable recovery before reporting failure. Otherwise a
            # later configuration GET could restart the gateway mid-response.
            # Process termination bypasses this handler and leaves the journal
            # for daemon-start recovery.
            self.recover()
            raise
        self.clear_journal()

    def discover(self, provider, api, credential):
        # The existing helper disables redirects/proxy inheritance and verifies
        # TLS. HTTP mock discovery needs a separately qualified fixture path.
        address = provider['urls'][api]
        if address.startswith('http://'):
            expected = 'http://pricetag-provider:' + ('18080/v1' if api == 'openai' else '18081')
            if address != expected or not (self.deploy / 'quadlets/pricetag-provider.container').is_file():
                raise ValueError('HTTP discovery is restricted to the dedicated mock fixture')
            script = """import json,sys,urllib.request
value=json.load(sys.stdin)
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs): return None
headers={'Authorization':'Bearer '+value['key']} if value['api']=='openai' else {'x-api-key':value['key'],'anthropic-version':'2023-06-01'}
port='18080' if value['api']=='openai' else '18081'
request=urllib.request.Request('http://127.0.0.1:'+port+'/v1/models',headers=headers)
with urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect()).open(request,timeout=10) as response:
 data=json.loads(response.read(2097152))
print(json.dumps([item['id'] for item in data['data']]))
"""
            result = self.providers.service('podman', 'exec', '-i', 'pricetag-provider', 'python3', '-c', script,
                input=json.dumps({'api': api, 'key': credential}).encode())
            if result.returncode:
                raise ValueError('mock discovery failed')
            models = json.loads(result.stdout)
            if not isinstance(models, list) or any(not isinstance(x, str) or len(x) > 200 for x in models):
                raise ValueError('invalid mock catalog')
            return sorted(set(models))
        previous = self.providers.MESSAGES_AUTH
        try:
            self.providers.MESSAGES_AUTH = provider['messages_auth']
            entries = self.providers.discover_models(provider['urls'][api], api, credential)
        finally:
            self.providers.MESSAGES_AUTH = previous
        return sorted({entry['id'] for entry in entries})
