#!/usr/bin/env python3
"""Install the pinned gateway, MaaS and PriceTag on a fresh RHEL host."""
import argparse
import ipaddress
import os
from pathlib import Path
import platform
import pwd
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MAAS_COMMIT = '6ac4c80ebc95f590e5f24593ac15bb80c7f9fa1d'
MAAS_REPO = 'https://github.com/Ladas/models-as-a-service.git'
METERING_REPO = 'https://github.com/redhat-et/pricetag-metering.git'
PRAXIS_IMAGE = 'quay.io/opendatahub/praxis-experimental@sha256:502f120fed7b8e516ce1d78396045c8f72673672351432b9dc2e61baf5c13ac8'
PRAXIS_REVISION = '5667c4acecd0981ae5114cbbf2ee3dcccec9c248'
MAAS_IMAGE = 'localhost/pricetag-maas:standalone'
METERING_IMAGE = 'localhost/pricetag-metering:upstream-557ceb1'
CACHE = Path('/var/cache/pricetag-installer')
DEPLOY = Path('/etc/praxis-pricetag')
ADMIN = Path('/root/pricetag-admin')
INPUTS = Path('/root/pricetag-provider-inputs')


def valid_hostname(value):
    try:
        ipaddress.IPv4Address(value)
        return True
    except ValueError:
        return len(value) <= 253 and all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', part)
                                         for part in value.split('.'))


def run(command, capture=False):
    command = [str(x) for x in command]
    print('+ ' + shlex.join(command), flush=True)
    result = subprocess.run(command, check=True, cwd='/tmp', text=True,
                            umask=0o022 if command[0] == 'git' else -1,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else None


def service_prefix():
    uid = pwd.getpwnam('praxis-svc').pw_uid
    return ['sudo', '-u', 'praxis-svc', 'env', f'XDG_RUNTIME_DIR=/run/user/{uid}',
            f'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus']


def import_image(image, prefix):
    # Stream between stores and check both processes; a failed save must not be
    # hidden by a successful load. Never use the administrator's cwd as praxis-svc.
    print('Importing into praxis-svc: ' + image, flush=True)
    source_id = run(['podman', 'image', 'inspect', image, '--format', '{{.Id}}'], True)
    if not re.fullmatch(r'(?:sha256:)?[0-9a-f]{64}', source_id):
        raise RuntimeError('source image ID is invalid')
    save = subprocess.Popen(['podman', 'save', image], stdout=subprocess.PIPE, cwd='/tmp')
    try:
        with save.stdout:
            loaded = subprocess.run(prefix + ['podman', 'load'], stdin=save.stdout, cwd='/tmp')
        saved = save.wait()
        if saved or loaded.returncode:
            raise RuntimeError('image export/import failed; no deployment prepared')
    finally:
        if save.poll() is None:
            save.terminate()
            save.wait()
    image_id = run(prefix + ['podman', 'image', 'inspect', source_id, '--format', '{{.Id}}'], True)
    if re.fullmatch(r'[0-9a-f]{64}', image_id):
        image_id = 'sha256:' + image_id
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id):
        raise RuntimeError('image import did not return an immutable image ID')
    return image_id


def checkout(repository, directory, revision=None):
    if directory.exists():
        # Never discard local changes or silently repurpose a cache checkout.
        if directory.is_symlink() or not (directory / '.git').is_dir():
            raise RuntimeError('invalid source cache: ' + str(directory))
        if run(['git', '-C', directory, 'remote', 'get-url', 'origin'], True) != repository:
            raise RuntimeError('source cache has an unexpected origin')
        if run(['git', '-C', directory, 'status', '--porcelain'], True):
            raise RuntimeError('source cache is dirty; review it before retrying')
    else:
        run(['git', 'clone', repository, directory])
    if revision:
        run(['git', '-C', directory, 'fetch', 'origin', revision])
        run(['git', '-C', directory, 'checkout', '--detach', revision])


def preflight(mode):
    if os.geteuid() != 0:
        raise ValueError('run with sudo on the RHEL host')
    if not re.search(r'^ID="?rhel"?$', Path('/etc/os-release').read_text(), re.M):
        raise ValueError('this installer supports RHEL only')
    if mode == 'mock' and not (ROOT / 'tests/common/provider.py').is_file():
        raise ValueError('incomplete checkout: tests/common/provider.py is required for mock mode')
    for path in (DEPLOY, ADMIN):
        if path.exists() or path.is_symlink():
            raise ValueError(f'{path} already exists; this is a fresh installer, not an upgrade command')
    if mode == 'mock' and INPUTS.exists():
        raise ValueError('mock installation refuses existing real-provider inputs')
    if CACHE.is_symlink() or (CACHE.exists() and (CACHE.stat().st_uid != 0 or CACHE.stat().st_mode & 0o022)):
        raise ValueError('source cache must be root-owned and not group/world writable')


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', choices=('real', 'mock'))
    p.add_argument('--hostname', help='public IPv4 or DNS name; no scheme, path or port')
    p.add_argument('--provider', action='append', choices=('openai', 'pricetag'), default=[],
                   help='real mode: repeat for both providers; credentials are prompted securely')
    p.add_argument('--openai-key-file', type=Path)
    p.add_argument('--pricetag-key-file', type=Path)
    p.add_argument('--pricetag-messages-url')
    p.add_argument('--pricetag-openai-url')
    p.add_argument('--monthly-usd', type=int, default=5)
    p.add_argument('--yes', action='store_true', help='skip installation confirmation, not credential prompts')
    p.add_argument('--plan', action='store_true', help='print the stages without changing the host')
    args = p.parse_args(argv)
    if not args.mode and sys.stdin.isatty() and not args.plan:
        args.mode = input('Deployment mode [real/mock]: ').strip()
    if not args.hostname and sys.stdin.isatty() and not args.plan:
        args.hostname = input('Gateway public IPv4 or DNS name: ').strip()
    if args.mode not in ('real', 'mock') or not args.hostname or not valid_hostname(args.hostname):
        p.error('provide --mode real|mock and --hostname with a valid IPv4 or DNS name')
    if not 1 <= args.monthly_usd <= 10000:
        p.error('--monthly-usd must be 1–10000')
    if args.mode == 'mock' and args.provider:
        p.error('mock mode cannot configure real providers')
    if args.mode == 'real' and not args.provider:
        if sys.stdin.isatty() and not args.plan:
            choice = input('Providers [openai/pricetag/both]: ').strip()
            args.provider = ['openai', 'pricetag'] if choice == 'both' else [choice]
        if not args.provider or any(x not in ('openai', 'pricetag') for x in args.provider):
            p.error('real mode requires --provider openai and/or --provider pricetag')
    for provider in ('openai', 'pricetag'):
        key_file = getattr(args, provider + '_key_file')
        if key_file and not key_file.is_absolute():
            p.error('credential file paths must be absolute')
        if key_file and provider not in args.provider:
            p.error('--' + provider + '-key-file requires that provider')
    if args.pricetag_messages_url or args.pricetag_openai_url:
        if 'pricetag' not in args.provider:
            p.error('PriceTag URLs require --provider pricetag')
    if args.pricetag_key_file and not (args.pricetag_messages_url or args.pricetag_openai_url):
        p.error('--pricetag-key-file requires a PriceTag URL')
    if not args.plan and not sys.stdin.isatty() and args.mode == 'real':
        if any(not getattr(args, provider + '_key_file') for provider in args.provider):
            p.error('noninteractive real installation requires a private key file for each provider')
    args.provider = list(dict.fromkeys(args.provider))
    return args


def main():
    args = parse_args()
    print(f'Fresh {args.mode} gateway: https://{args.hostname}:8443; monthly USD allowance: {args.monthly_usd}')
    print('1. Install RHEL packages and prepare praxis-svc.')
    print('2. Build pinned MaaS/PriceTag images; pull pinned Praxis; import into praxis-svc.')
    print('3. Configure selected providers through hidden prompts or private files (mock: synthetic provider only).')
    print('4. Generate TLS/configuration and start Quadlets; verify HTTPS readiness.')
    print('5. Print CA/key paths. Keys and provider credentials are not printed.')
    print('No AWS security-group changes, upgrades, backups or existing-data adoption.')
    if args.plan:
        print('MaaS commit: ' + MAAS_COMMIT + '\nPraxis image: ' + PRAXIS_IMAGE)
        return
    preflight(args.mode)
    if not args.yes and input('Install on this host? Type install: ').strip() != 'install':
        raise ValueError('installation cancelled')
    arch = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(platform.machine())
    if not arch:
        raise ValueError('supported architectures are x86_64 and aarch64')
    os.umask(0o077)
    run(['dnf', 'install', '-y', 'podman', 'git', 'python3', 'python3-pyyaml', 'openssl',
         'curl', 'sudo', 'policycoreutils-python-utils', 'shadow-utils'])
    run([ROOT / 'scripts/common/install', '--prepare'])
    prefix = service_prefix()
    # Refuse retained data or Quadlets even if someone removed the config directory.
    if subprocess.run(prefix + ['podman', 'volume', 'exists', 'pricetag-data'], cwd='/tmp').returncode != 1:
        raise ValueError('existing data volume or storage error; review the host instead of reinstalling')
    uid = pwd.getpwnam('praxis-svc').pw_uid
    units = Path(f'/etc/containers/systemd/users/{uid}')
    if list(units.glob('pricetag*')):
        raise ValueError('existing PriceTag Quadlets; review the host instead of reinstalling')
    CACHE.mkdir(mode=0o700, parents=True, exist_ok=True)
    checkout(MAAS_REPO, CACHE / 'maas', MAAS_COMMIT)
    checkout(METERING_REPO, CACHE / 'metering')
    run([ROOT / 'scripts/pricetag/build-maas', '--source', CACHE / 'maas',
         '--expected-commit', MAAS_COMMIT, '--platform', 'linux/' + arch])
    run([sys.executable, ROOT / 'scripts/pricetag/build-metering', '--source', CACHE / 'metering',
         '--platform', 'linux/' + arch])
    run(['podman', 'pull', PRAXIS_IMAGE])
    revision = run(['podman', 'image', 'inspect', PRAXIS_IMAGE, '--format',
                    '{{index .Labels "org.opencontainers.image.revision"}}'], True)
    if revision != PRAXIS_REVISION:
        raise ValueError('Praxis source label does not match the pinned release')
    ids = [import_image(image, prefix) for image in (PRAXIS_IMAGE, MAAS_IMAGE, METERING_IMAGE)]
    for provider in args.provider:
        setup = [sys.executable, ROOT / 'scripts/pricetag/providers', provider]
        key_file = getattr(args, provider + '_key_file')
        if key_file:
            setup += ['--key-file', key_file]
        if provider == 'pricetag':
            for option, address in (('--anthropic-url', args.pricetag_messages_url),
                                    ('--openai-url', args.pricetag_openai_url)):
                if address:
                    setup += [option, address]
        run(setup)
    command = [sys.executable, ROOT / 'scripts/pricetag/prepare.py', '--hostname', args.hostname,
               '--praxis-image', ids[0], '--maas-image', ids[1], '--metering-image', ids[2],
               '--monthly-usd', str(args.monthly_usd)]
    if args.mode == 'mock':
        command += ['--mock-provider', '--price-sources', ROOT / 'configs/pricetag/perf-price-sources.json']
    else:
        run([sys.executable, ROOT / 'scripts/pricetag/providers', 'export'])
        for option, filename in (('--providers', 'providers.json'), ('--models', 'models.json'),
                                 ('--provider-unit', 'provider-secrets.container'), ('--price-sources', 'prices.json')):
            command += [option, INPUTS / filename]
    run(command)
    run([ROOT / 'scripts/pricetag/start'])
    run(['curl', '--noproxy', '*', '--fail', '--silent', '--show-error', '--cacert',
         DEPLOY / 'ca.pem', 'https://localhost:8443/login', '--output', '/dev/null'])
    print('\nReady: https://' + args.hostname + ':8443/login')
    print('CA: /etc/praxis-pricetag/ca.pem')
    print('Keys: /root/pricetag-admin/{admin,alice,bob}.key')
    print('Continue with docs/quickstarts/remote-gateway-pricetag/users.md and the client steps in docs/quickstarts/remote-gateway-pricetag/README.md.')
    if args.mode == 'mock':
        print('Benchmark: sudo python3 scripts/pricetag/benchmark')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, EOFError, KeyboardInterrupt) as error:
        print(f'Installation stopped: {error}', file=sys.stderr)
        print('No files or volumes were automatically deleted. Fix the failed stage and use the manual steps; '
              'if configuration was already prepared, inspect it before running scripts/pricetag/start.', file=sys.stderr)
        sys.exit(1)
