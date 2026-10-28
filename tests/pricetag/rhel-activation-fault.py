#!/usr/bin/env python3
"""Arm/remove a one-shot gateway start failure on the dedicated mock benchmark."""
import argparse
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import pwd
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('arm', 'disarm'))
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('run as root on the benchmark VM')
    loader = importlib.machinery.SourceFileLoader('benchmark', str(ROOT / 'scripts/pricetag/benchmark'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec); loader.exec_module(module)
    module.require_mock(Path('/etc/praxis-pricetag'))
    uid = pwd.getpwnam('praxis-svc').pw_uid
    runtime = Path('/run/user') / str(uid)
    script = runtime / 'pricetag-test-fail-start.py'
    marker = runtime / 'pricetag-test-fail-next-start'
    dropin = runtime / 'systemd/user/pricetag-gateway.service.d/pricetag-test-failure.conf'
    service = ['sudo', '-u', 'praxis-svc', 'env', f'XDG_RUNTIME_DIR={runtime}',
               f'DBUS_SESSION_BUS_ADDRESS=unix:path={runtime}/bus']
    if args.command == 'arm':
        if any(p.exists() or p.is_symlink() for p in (script, marker, dropin)):
            raise ValueError('test fault already exists; disarm it first')
        script.write_text('from pathlib import Path\np=Path(' + repr(str(marker)) + ')\n'
                          'if p.exists():\n p.unlink()\n raise SystemExit(1)\n')
        script.chmod(0o644)
        marker.touch(mode=0o600)
        os.chown(marker, uid, -1)
        dropin.parent.mkdir(parents=True, exist_ok=True)
        dropin.write_text('[Service]\nExecStartPre=/usr/bin/python3 ' + str(script) + '\n')
        dropin.chmod(0o644)
    else:
        for p in (dropin, marker, script):
            p.unlink(missing_ok=True)
    subprocess.run(service + ['systemctl', '--user', 'daemon-reload'], cwd='/tmp', check=True)
    print('One-shot mock gateway fault ' + ('armed; the next start fails once.' if args.command == 'arm' else 'removed.'))


if __name__ == '__main__':
    main()
