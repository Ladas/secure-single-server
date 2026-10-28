#!/usr/bin/env python3
"""Disposable Podman deployment for the demo CI suite; never use an installed host."""
import argparse
import importlib.machinery
import importlib.util
import json
import ipaddress
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = Path('/etc/praxis-pricetag')
ADMIN = Path('/root/pricetag-admin')
sys.path.insert(0, str(ROOT / 'scripts/pricetag'))
from prepare import POSTGRES, PYTHON


def run(command, **options):
    return subprocess.run(list(map(str, command)), check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, **options).stdout.strip()


def podman(*args):
    return run(['podman', *args])


def ready(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(90):
        try:
            with opener.open(url, timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(1)
    raise RuntimeError('service readiness timeout')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--maas-image', required=True)
    parser.add_argument('--metering-image', required=True)
    parser.add_argument('--praxis-image', required=True)
    parser.add_argument('--node-modules', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0 or DEPLOY.exists() or DEPLOY.is_symlink() or ADMIN.exists() or ADMIN.is_symlink():
        parser.error('requires root on a disposable host without an existing deployment')
    if not args.node_modules.is_absolute() or not args.output.is_absolute():
        parser.error('use absolute node-modules and output paths')
    os.umask(0o077)
    args.output.mkdir(mode=0o700)
    try:
        pwd.getpwnam('praxis-svc')
    except KeyError:
        run(['useradd', '--system', '--no-create-home', '--shell', '/usr/sbin/nologin', 'praxis-svc'])
    prefix = 'pricetag-ci-' + uuid.uuid4().hex[:10]
    networks, containers = [], []
    stage = 'prepare'
    try:
        images = []
        for image in (args.praxis_image, args.maas_image, args.metering_image):
            info = json.loads(podman('image', 'inspect', image))[0]
            images.append('sha256:' + info['Id'].removeprefix('sha256:'))
        with tempfile.TemporaryDirectory(prefix='pricetag-ci-') as temporary:
            sources = Path(temporary) / 'prices.json'
            sources.write_text('{}')
            run([sys.executable, ROOT / 'scripts/pricetag/prepare.py', '--hostname', 'localhost',
                 '--praxis-image', images[0], '--maas-image', images[1], '--metering-image', images[2],
                 '--mock-provider', '--managed-mock', '--price-sources', sources])
        # Container UID 1001 needs the generated test mounts; parents stay private.
        for path in (DEPLOY / 'gateway').iterdir():
            path.chmod(0o644)
        (DEPLOY / 'gateway').chmod(0o755)
        (DEPLOY / 'initdb').chmod(0o755)
        (DEPLOY / 'maas-db-url').chmod(0o644)
        for path in (DEPLOY / 'initdb').iterdir():
            path.chmod(0o644)
        (DEPLOY / 'm2m-secret').chmod(0o644)
        (DEPLOY / 'catalog').chmod(0o755)
        (DEPLOY / 'catalog/models.json').chmod(0o644)
        for suffix in ('private', 'mock'):
            name = prefix + '-' + suffix
            podman('network', 'create', name)
            networks.append(name)
        private, mock = networks
        subnet = json.loads(podman('network', 'inspect', private))[0]['subnets'][0]
        gateway = subnet['gateway']
        praxis_ip = str(ipaddress.ip_network(subnet['subnet']).network_address + 11)
        def start(role, image, network, *options):
            name = prefix + '-' + role
            containers.append(name)
            podman('run', '-d', '--name', name, '--network', network,
                   '--network-alias', 'pricetag-' + role,
                   *([] if role == 'db' else ['--cap-drop', 'all']),
                   '--security-opt', 'no-new-privileges', *options, image)
            return name
        stage = 'postgres'
        db = start('db', POSTGRES, private, '--env-file', DEPLOY / 'postgres.env',
                   '--tmpfs', '/var/lib/postgresql/data:rw',
                   '-v', str(DEPLOY / 'initdb') + ':/docker-entrypoint-initdb.d:ro,Z')
        for _ in range(90):
            try:
                podman('exec', db, 'psql', '-U', 'postgres', '-d', 'maas', '-Atc', 'SELECT 1')
                break
            except subprocess.CalledProcessError:
                time.sleep(1)
        else:
            raise RuntimeError('database bootstrap failed')
        stage = 'maas'
        maas = start('maas', images[1], private, '--read-only', '--user', '1001:1001',
                    '-p', '127.0.0.1:18086:8080',
                    '-v', str(DEPLOY / 'maas-db-url') + ':/run/secrets/db:ro,Z',
                    '-e', 'DB_CONNECTION_URL_FILE=/run/secrets/db',
                    '-e', 'MAAS_RUNTIME_MODE=standalone', '-e', 'MAAS_SUBSCRIPTION_MODE=standalone',
                    '-e', 'ADDRESS=:8080', '-e', 'SECURE=false', '-e', 'API_KEY_MAX_EXPIRATION_DAYS=90',
                    '-e', 'MAAS_ADMIN_GROUPS=single-server-admin',
                    '-e', 'METRICS_SECURE=false', '-e', 'METRICS_ADDRESS=127.0.0.1:9090',
                    '-e', 'MAAS_TRUSTED_PROXY_CIDRS=' + gateway + '/32')
        ready('http://127.0.0.1:18086/health')
        # Only the metering container and loopback-published host mint keys.
        stage = 'metering'
        meter = start('metering', images[2], private, '--read-only', '--user', '1001:1001',
                      '-p', '127.0.0.1:18087:8080', '--env-file', DEPLOY / 'metering.env',
                      '-v', str(DEPLOY / 'catalog') + ':/etc/gateway-catalog:ro,Z')
        meter_ip = json.loads(podman('inspect', meter))[0]['NetworkSettings']['Networks'][private]['IPAddress']
        podman('rm', '-f', maas)
        containers.remove(maas)
        # Recreate with the specific metering peer address, not the whole subnet.
        maas = start('maas', images[1], private, '--read-only', '--user', '1001:1001',
                    '-p', '127.0.0.1:18086:8080', '-v', str(DEPLOY / 'maas-db-url') + ':/run/secrets/db:ro,Z',
                    '-e', 'DB_CONNECTION_URL_FILE=/run/secrets/db',
                    '-e', 'MAAS_RUNTIME_MODE=standalone', '-e', 'MAAS_SUBSCRIPTION_MODE=standalone',
                    '-e', 'ADDRESS=:8080', '-e', 'SECURE=false', '-e', 'API_KEY_MAX_EXPIRATION_DAYS=90',
                    '-e', 'MAAS_ADMIN_GROUPS=single-server-admin',
                    '-e', 'METRICS_SECURE=false', '-e', 'METRICS_ADDRESS=127.0.0.1:9090',
                    '-e', 'MAAS_TRUSTED_PROXY_CIDRS=' + gateway + '/32,' + meter_ip + '/32,' + praxis_ip + '/32')
        ready('http://127.0.0.1:18086/health')
        ready('http://127.0.0.1:18087/ready')
        stage = 'bootstrap APIs'
        run([sys.executable, ROOT / 'scripts/pricetag/maas-key', 'create', '--subject', 'admin',
             '--admin', '--name', 'admin', '--output', ADMIN / 'admin.key'])
        from metering_admin import provision, bootstrap
        provision('admin', 'Administrator', admin=True)
        bootstrap(DEPLOY / 'bootstrap.json')
        for subject in ('alice', 'bob'):
            run([sys.executable, ROOT / 'scripts/pricetag/user', '--subject', subject,
                 '--name', subject, '--output', ADMIN / (subject + '.key')])
        stage = 'mock provider'
        # The fixture image's default entrypoint is python; specify the script.
        name = prefix + '-provider'
        containers.append(name)
        podman('run', '-d', '--name', name, '--network', mock, '--network-alias', 'pricetag-provider',
               '--cap-drop', 'all', '--security-opt', 'no-new-privileges', '--read-only',
               '-e', 'MOCK_MANAGEMENT=1', '-v', str(DEPLOY / 'fixtures') + ':/fixtures:ro,Z',
               PYTHON, 'python3', '/fixtures/run.py')
        stage = 'praxis'
        name = prefix + '-gateway'
        containers.append(name)
        podman('run', '-d', '--name', name, '--network', private + ':ip=' + praxis_ip, '--network', mock,
               '--cap-drop', 'all', '--security-opt', 'no-new-privileges', '--read-only',
               '-p', '127.0.0.1:8443:8443', '-e', 'CUSTOM_MOCK_API_KEY=synthetic-anthropic',
               '-v', str(DEPLOY / 'gateway') + ':/etc/praxis:ro,Z',
               '-v', str(DEPLOY / 'm2m-secret') + ':/run/secrets/pricetag-m2m:ro,Z',
               images[0], '-c', '/etc/praxis/gateway.json')
        for _ in range(60):
            result = subprocess.run(['curl', '--noproxy', '*', '--fail', '--silent', '--cacert',
                                     str(DEPLOY / 'ca.pem'), 'https://localhost:8443/login', '-o', '/dev/null'],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('gateway HTTPS readiness failed')
        stage = 'demo suite'
        # Logs and credentials remain private. Only results.json is published.
        with (args.output / 'suite-private.log').open('w') as log:
            subprocess.run([sys.executable, str(ROOT / 'tests/pricetag/demo-suite'),
                            '--output', str(args.output / 'suite'), '--node-modules', str(args.node_modules)],
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1800)
        shutil.copyfile(args.output / 'suite/results.json', args.output / 'results.json')
        print('PASS: disposable demo deployment and API/browser/quota suite')
    except Exception as error:
        if (args.output / 'suite/results.json').is_file():
            shutil.copyfile(args.output / 'suite/results.json', args.output / 'results.json')
        with (args.output / 'diagnostics-private.log').open('w') as log:
            traceback.print_exc(file=log)
            if isinstance(error, subprocess.CalledProcessError):
                log.write(error.stdout or '')
                log.write(error.stderr or '')
            for container in containers:
                subprocess.run(['podman', 'logs', '--tail', '30', container], stdout=log, stderr=log)
        (args.output / 'failure.json').write_text(json.dumps({'passed': False, 'stage': stage}) + '\n')
        print('FAIL: ' + stage + '; private diagnostics retained, no credentials printed', file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        for name in reversed(containers):
            subprocess.run(['podman', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for name in reversed(networks):
            subprocess.run(['podman', 'network', 'rm', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # These exact directories were absent at entry and belong to this test.
        shutil.rmtree(DEPLOY, ignore_errors=True)
        shutil.rmtree(ADMIN, ignore_errors=True)


if __name__ == '__main__':
    main()
