#!/usr/bin/env python3
"""Smoke-test the two application images against disposable PostgreSQL."""
import argparse
import json
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/pricetag'))
from prepare import POSTGRES


def podman(*args, **kwargs):
    return subprocess.run(['podman', *map(str, args)], check=True, text=True,
                          stdout=subprocess.PIPE, **kwargs).stdout.strip()


def status(url, data=None):
    request = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=3) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def ready(url):
    for _ in range(90):
        try:
            if status(url) == 200:
                return
        except OSError:
            pass
        time.sleep(1)
    raise RuntimeError('Service did not become ready: ' + url)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--maas-image', required=True)
    parser.add_argument('--metering-image', required=True)
    args = parser.parse_args()
    prefix = 'pricetag-ci-' + uuid.uuid4().hex[:12]
    containers = [prefix + '-' + role for role in ('db', 'maas', 'metering')]
    db, maas, metering = containers
    podman('network', 'create', prefix)
    try:
        network = json.loads(podman('network', 'inspect', prefix))[0]
        gateway = network['subnets'][0]['gateway']
        with tempfile.TemporaryDirectory(prefix='pricetag-image-test-') as directory:
            root = Path(directory)
            # Synthetic credentials only; nothing is published beyond loopback.
            password = secrets.token_hex(24)
            pg_env = root / 'postgres.env'
            pg_env.write_text('POSTGRES_PASSWORD=' + password + '\n')
            pg_env.chmod(0o600)
            podman('run', '-d', '--name', db, '--network', prefix, '--network-alias', 'db',
                   '--env-file', pg_env, '--tmpfs', '/var/lib/postgresql/data', POSTGRES)
            for _ in range(90):
                if subprocess.run(['podman', 'exec', db, 'pg_isready', '-U', 'postgres'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                    break
                time.sleep(1)
            else:
                raise RuntimeError('PostgreSQL did not become ready')
            for database in ('maas', 'metering'):
                podman('exec', db, 'createdb', '-U', 'postgres', database)
            dsn = root / 'maas-dsn'
            dsn.write_text(f'postgres://postgres:{password}@db:5432/maas?sslmode=disable\n')
            # Only this file is mounted; the host's temporary directory stays
            # private while container UID 1001 can read the synthetic DSN.
            dsn.chmod(0o644)
            common = ['--network', prefix, '--read-only', '--cap-drop', 'all',
                      '--security-opt', 'no-new-privileges', '--user', '1001:1001',
                      '-p', '127.0.0.1::8080']
            podman('run', '-d', '--name', maas, *common, '--network-alias', 'maas',
                   '-v', str(dsn) + ':/run/secrets/db-url:ro,Z',
                   '-e', 'MAAS_RUNTIME_MODE=standalone', '-e', 'MAAS_SUBSCRIPTION_MODE=standalone',
                   '-e', 'ADDRESS=:8080', '-e', 'SECURE=false',
                   '-e', 'DB_CONNECTION_URL_FILE=/run/secrets/db-url',
                   '-e', 'MAAS_ADMIN_GROUPS=single-server-admin',
                   '-e', 'MAAS_TRUSTED_PROXY_CIDRS=127.0.0.1/32,' + gateway + '/32',
                   '-e', 'METRICS_SECURE=false', '-e', 'METRICS_ADDRESS=127.0.0.1:9090', args.maas_image)
            maas_url = 'http://' + podman('port', maas, '8080/tcp')
            ready(maas_url + '/health')
            env = root / 'metering.env'
            env.write_text(f'DATABASE_URL=postgres://postgres:{password}@db:5432/metering?sslmode=disable\n'
                           'M2M_AUTH_REQUIRED=true\nM2M_SHARED_SECRET=' + secrets.token_hex(32) + '\n'
                           'SESSION_SECRET=' + secrets.token_hex(32) + '\n'
                           'MAAS_VALIDATE_URL=http://maas:8080/internal/v1/api-keys/validate\n')
            env.chmod(0o600)
            podman('run', '-d', '--name', metering, *common, '--env-file', env, args.metering_image)
            metering_url = 'http://' + podman('port', metering, '8080/tcp')
            ready(metering_url + '/ready')
            if status(metering_url + '/api/v1/events', b'{}') != 401:
                raise RuntimeError('Metering accepted a request without machine credentials')
            # Both services migrated their own empty database without Kubernetes.
            for database in ('maas', 'metering'):
                count = podman('exec', db, 'psql', '-U', 'postgres', '-d', database, '-Atc',
                               "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
                if int(count) == 0:
                    raise RuntimeError(database + ' migrations created no tables')
            print('PASS: standalone readiness, database migrations and metering authentication')
    except Exception:
        for container in containers:
            subprocess.run(['podman', 'logs', '--tail', '30', container], check=False)
        raise
    finally:
        for container in reversed(containers):
            subprocess.run(['podman', 'rm', '-f', container], check=False, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        subprocess.run(['podman', 'network', 'rm', prefix], check=False, stdout=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
