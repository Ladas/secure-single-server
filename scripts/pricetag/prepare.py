#!/usr/bin/env python3
"""Prepare an isolated rootless Quadlet deployment; do not start services."""
import argparse
import copy
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shutil
import subprocess

from gateway import render

ROOT = Path(__file__).resolve().parents[2]
POSTGRES = 'docker.io/library/postgres@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea'
PYTHON = 'docker.io/library/python@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7'


def literal(value):
    return "'" + value.replace("'", "''") + "'"


def vllm_only(original, models):
    selected = [m for m in models if m['provider'] == 'vllm']
    if not selected:
        raise ValueError('vLLM-only deployment requires a local vLLM model')
    config = copy.deepcopy(original)
    for chain in config['filter_chains']:
        chain['filters'] = [f for f in chain['filters'] if f['filter'] != 'credential_injection']
        for item in chain['filters']:
            if item['filter'] == 'load_balancer':
                item['clusters'] = [c for c in item['clusters'] if c['name'] == 'vllm']
    return config, selected


def mock_inputs():
    models = [{'id': 'demo-model', 'provider': 'vllm', 'model': 'fixture',
               'apis': ['openai', 'anthropic'], 'context': 32768, 'output': 4096}]
    config = {'filter_chains': [{'name': api, 'filters': [
        {'filter': 'headers', 'request_remove': ['Authorization', 'X-Api-Key']},
        {'filter': 'load_balancer', 'clusters': [{'name': 'vllm',
         'endpoints': ['pricetag-provider:' + port]}]}]}
        for api, port in [('openai', '18080'), ('anthropic', '18081')]]}
    return config, models


def bootstrap(models, sources, budget):
    statements = ['BEGIN;',
        'CREATE UNIQUE INDEX IF NOT EXISTS uq_usage_events_event_id ON usage_events(event_id);',
        f"UPDATE quota_policy SET enforced=true, default_monthly_usd={budget}, "
        "allowed_over_limit_models='{}', over_cap_ceiling_usd=NULL;"]
    fields = 'input_cost_per_mtok,output_cost_per_mtok,cache_write_cost_per_mtok,cache_read_cost_per_mtok'
    for model in models:
        alias, source = literal(model['id']), literal(sources.get(model['id'], model['model']))
        statements += [
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM model_pricing WHERE model={source}) "
            f"THEN RAISE EXCEPTION 'Missing reviewed price for model %', {alias}; END IF; END $$;",
            f'INSERT INTO model_pricing(model,provider,{fields}) '
            f'SELECT {alias},{literal(model["provider"])},{fields} FROM model_pricing WHERE model={source} '
            'ON CONFLICT(model) DO NOTHING;']
    statements += ['COMMIT;']
    return '\n'.join(statements) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--providers', type=Path, default=Path('/etc/praxis/shared-gateway.yaml'))
    parser.add_argument('--models', type=Path, default=Path('/etc/praxis/unified-models.json'))
    parser.add_argument('--provider-unit', type=Path)
    parser.add_argument('--praxis-image', required=True, help='local immutable image ID containing manual_jwt')
    parser.add_argument('--metering-image', required=True, help='local image ID sha256:... in praxis-svc storage')
    parser.add_argument('--hostname', required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--vllm-only', action='store_true',
                        help='expose only local vLLM; do not mount cloud provider secrets')
    mode.add_argument('--mock-provider', action='store_true',
                      help='isolated synthetic provider for a fresh performance-test VM')
    parser.add_argument('--monthly-usd', type=int, default=5)
    parser.add_argument('--price-sources', type=Path, required=True,
                        help='JSON mapping gateway aliases to reviewed PriceTag pricing model IDs')
    parser.add_argument('--directory', type=Path, default=Path('/etc/praxis-pricetag'))
    parser.add_argument('--admin-directory', type=Path, default=Path('/root/pricetag-admin'))
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('run as root on the RHEL host')
    if not args.mock_provider and args.provider_unit is None:
        parser.error('--provider-unit is required unless --mock-provider is selected')
    if not all(re.fullmatch(r'sha256:[0-9a-f]{64}', image) for image in (args.metering_image, args.praxis_image)):
        parser.error('image arguments must be immutable local sha256 image IDs')
    if not 1 <= args.monthly_usd <= 10000:
        parser.error('monthly-usd must be 1–10000')
    for directory in (args.directory, args.admin_directory):
        if not directory.is_absolute() or re.search(r'[\s%]', str(directory)) or directory.exists():
            parser.error('use new absolute directories without whitespace or percent signs')
    owner = pwd.getpwnam('praxis-svc')
    if args.mock_provider:
        original, models = mock_inputs()
    else:
        models = json.loads(args.models.read_text())
        original = json.loads(args.providers.read_text())
    if args.vllm_only:
        original, models = vllm_only(original, models)
    config = render(original, models,
                    list(dict.fromkeys([f'https://{args.hostname}:8443', 'https://localhost:8443'])))
    sources = json.loads(args.price_sources.read_text())
    if not isinstance(sources, dict) or any(not isinstance(v, str) for v in sources.values()):
        parser.error('price-sources must map aliases to model names')
    if any(m['id'] == sources.get(m['id'], m['model']) for m in models):
        parser.error('use distinct gateway aliases to keep their initial pricing snapshot stable')
    provider_secrets = []
    for line in ([] if args.mock_provider else args.provider_unit.read_text().splitlines()):
        if re.fullmatch(r'Secret=[A-Za-z0-9_.-]+,type=env,target=[A-Z0-9_]+_API_KEY', line):
            provider_secrets.append(line)
    needed = {entry['env_var'] for chain in config['filter_chains'] for f in chain['filters']
              if f['filter'] == 'credential_injection' for entry in f['clusters']
              if 'env_var' in entry and entry['env_var'] != 'M2M_SHARED_SECRET'}
    supplied = {line.rsplit('=', 1)[1] for line in provider_secrets}
    if not needed <= supplied:
        parser.error('provider Quadlet does not supply every required API-key secret')
    provider_secrets = [line for line in provider_secrets if line.rsplit('=', 1)[1] in needed]
    os.umask(0o077)
    args.admin_directory.mkdir(mode=0o700)
    args.directory.mkdir(mode=0o750)
    bundle = args.directory / 'gateway'
    units = args.directory / 'quadlets'
    bundle.mkdir(mode=0o750)
    units.mkdir(mode=0o750)
    credential = ROOT / 'scripts/remote-gateway/credentials'

    def credentials(*options):
        subprocess.run([str(credential), *map(str, options)], check=True, stdout=subprocess.DEVNULL)

    credentials('init-jwt', '--directory', args.admin_directory / 'issuer')
    credentials('lab-tls', '--directory', args.admin_directory / 'tls', '--hostname', args.hostname,
                '--alt-hostname', 'localhost', '--alt-hostname', '127.0.0.1')
    manual = ROOT / 'scripts/pricetag/credentials'
    subprocess.run([str(manual), 'init', '--registry', str(bundle / 'users.json')], check=True)
    for subject in ('admin', 'alice', 'bob'):
        subprocess.run([str(manual), 'issue', '--key', str(args.admin_directory / 'issuer/private.pem'),
            '--registry', str(bundle / 'users.json'), '--subject', subject,
            '--output', str(args.admin_directory / (subject + '.jwt'))], check=True)
    for source, target in [(args.admin_directory / 'issuer/public.pem', 'jwt-public.pem'),
                           (args.admin_directory / 'tls/server.pem', 'tls.pem'),
                           (args.admin_directory / 'tls/server-key.pem', 'tls-key.pem')]:
        shutil.copyfile(source, bundle / target)
    (bundle / 'gateway.json').write_text(json.dumps(config, indent=2) + '\n')
    shutil.copyfile(args.admin_directory / 'tls/ca.pem', args.directory / 'ca.pem')
    password, m2m = secrets.token_hex(32), secrets.token_hex(32)

    def env(name, values):
        (args.directory / name).write_text(''.join(f'{k}={v}\n' for k, v in values.items()))

    env('postgres.env', {'POSTGRES_USER': 'metering', 'POSTGRES_DB': 'metering',
                        'POSTGRES_PASSWORD': password, 'TZ': 'UTC', 'PGTZ': 'UTC'})
    env('metering.env', {'DATABASE_URL': f'postgres://metering:{password}@pricetag-db:5432/metering?sslmode=disable',
        'M2M_AUTH_REQUIRED': 'true', 'M2M_SHARED_SECRET': m2m, 'SESSION_SECRET': secrets.token_hex(32),
        'SUPERADMIN_USERS': 'admin', 'MONTHLY_TOKEN_QUOTA': '10000000000', 'TZ': 'UTC',
        'MAAS_VALIDATE_URL': 'http://pricetag-gateway:18084/validate'})
    env('gateway.env', {'M2M_SHARED_SECRET': m2m})
    (args.directory / 'bootstrap.sql').write_text(bootstrap(models, sources, args.monthly_usd))
    (args.directory / 'models.json').write_text(json.dumps(models, indent=2) + '\n')
    (args.directory / 'price-sources.json').write_text(json.dumps(sources, indent=2) + '\n')
    (units / 'pricetag.network').write_text('[Network]\nNetworkName=pricetag-private\nDriver=bridge\n')
    (units / 'pricetag-db.volume').write_text('[Volume]\nVolumeName=pricetag-data\n')
    common = 'ReadOnly=true\nNoNewPrivileges=true\n'
    app = common + 'User=1001\nGroup=1001\nUserNS=keep-id:uid=1001,gid=1001\nDropCapability=all\n'
    mount = f'Volume={bundle}:/etc/praxis:ro\n'

    def container(name, description, dependencies, body, memory):
        (units / (name + '.container')).write_text(
            f'[Unit]\nDescription={description}\nWants=network-online.target\nAfter=network-online.target {dependencies}\n'
            f'Requires={dependencies}\n\n[Container]\nContainerName={name}\nNetwork=pricetag.network\n'
            f'{body}\n[Service]\nRestart=on-failure\nRestartSec=5\nTimeoutStartSec=900\n'
            f'MemoryMax={memory}\n\n[Install]\nWantedBy=default.target\n')

    container('pricetag-db', 'PriceTag PostgreSQL', '',
        f'Image={POSTGRES}\nEnvironmentFile={args.directory}/postgres.env\n'
        'Volume=pricetag-db.volume:/var/lib/postgresql/data\n'
        'Tmpfs=/var/run/postgresql:rw,mode=3775\nTmpfs=/tmp\n'
        'HealthCmd=pg_isready -U metering -d metering\nHealthInterval=10s\n' + common, '1G')
    container('pricetag-metering', 'PriceTag metering and dashboards', 'pricetag-db.service',
        f'Image={args.metering_image}\nPull=never\nNetworkAlias=pricetag-metering\n'
        f'EnvironmentFile={args.directory}/metering.env\n' + app, '2G')
    network = '' if args.mock_provider else 'Network=praxis.network\n'
    dependencies = 'pricetag-metering.service'
    if args.mock_provider:
        fixtures = args.directory / 'fixtures'
        fixtures.mkdir()
        shutil.copyfile(ROOT / 'tests/common/provider.py', fixtures / 'provider.py')
        shutil.copyfile(ROOT / 'tests/pricetag/provider.py', fixtures / 'run.py')
        container('pricetag-provider', 'Synthetic LLM for performance testing only', '',
            f'Image={PYTHON}\nVolume={fixtures}:/fixtures:ro\nEnvironment=MOCK_STREAM_DELAY=1\n'
            'Exec=python3 /fixtures/run.py\n' + app, '1G')
        dependencies += ' pricetag-provider.service'
    container('pricetag-gateway', 'Praxis HTTPS gateway with per-user USD budgets', dependencies,
        f'Image={args.praxis_image}\nPull=never\nNetworkAlias=pricetag-gateway\n{network}PublishPort=0.0.0.0:8443:8443\n'
        f'EnvironmentFile={args.directory}/gateway.env\n' + '\n'.join(provider_secrets) + '\n' +
        mount + 'Exec=-c /etc/praxis/gateway.json\n' + app, '1G')
    for path in [args.directory, *args.directory.rglob('*')]:
        os.chown(path, 0, owner.pw_gid)
        path.chmod(0o750 if path.is_dir() else 0o640)
    print(f'Prepared {args.directory}; no services started. Administrator credentials: {args.admin_directory}')


if __name__ == '__main__':
    main()
