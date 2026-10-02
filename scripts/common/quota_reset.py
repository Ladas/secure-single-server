#!/usr/bin/env python3
"""Preview selected Valkey quota resets; --apply clears usage and restarts Praxis."""
import argparse
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess

import quota_config
from quota_manage import listing
import quota_status
import provider_manage

# The managed ACL permits expiry, not DEL/FLUSH. Expire exact ledger keys only;
# retain the namespace-wide reservation sequence and every unselected ledger.
RESET = """
local removed = 0
for _, key in ipairs(KEYS) do
  removed = removed + redis.call('PEXPIRE', key, 0)
end
return removed
"""


def selected_rules(config, *, provider=None, names=None):
    rows = listing(config, provider=provider, names=names)['rules']
    if not rows:
        raise ValueError('no matching enabled rules; run quota-reset --list')
    entries = quota_config.entries(config)
    selected = []
    for row in rows:
        item, rule = entries[row['rule']]
        backend = item.get('backend', {})
        if (backend.get('kind') != 'valkey' or item.get('key', 'global') != 'global'
                or rule.get('algorithm') != 'sliding_window'
                or backend.get('url') != '${TOKEN_RATE_LIMIT_VALKEY_URL}'
                or not backend.get('namespace', '').startswith('secure-single-server:limits:')):
            raise ValueError(row['rule'] + ': reset requires a managed global Valkey sliding-window rule')
        selected.append((backend['namespace'], rule['name']))
    return selected


def reset(config, *, provider=None, names=None, apply=False):
    if not provider and not names:
        raise ValueError('select --provider or one or more --rule values')
    selected = selected_rules(config, provider=provider, names=names)
    print('Reset consumed tokens and outstanding reservations for:')
    for _, name in selected:
        print('  ' + name)
    print('Capacities and all unselected budgets are retained. Applying briefly stops Praxis; '
          'active requests are interrupted. vLLM keeps running.', flush=True)
    if not apply:
        print('Preview only. Append --apply to reset these quotas.')
        return
    image = json.loads(quota_status.service('podman', 'inspect', 'praxis-shared-gateway',
                                           '--format', '{{json .ImageName}}'))
    if image.rsplit('@', 1)[-1] != quota_status.LEDGER_IMAGE:
        raise ValueError('quota reset is not qualified for this Praxis image')
    query = quota_status.valkey_client()  # Capture privately before stopping Praxis.
    keys = [key for namespace, name in selected for key in quota_status.valkey_keys(namespace, name)]
    try:
        provider_manage.service('systemctl', '--user', 'stop', 'praxis.service')
        result = json.loads(query('EVAL', RESET, str(len(keys)), *keys))
        if type(result) is not int or not 0 <= result <= len(keys):
            raise ValueError('Valkey did not confirm the reset; inspect quota-status before retrying')
    finally:
        provider_manage.restart()
    print('Selected quotas reset; Praxis is healthy. Check: sudo scripts/common/quota-status')


def parse_args(argv=None):
    parser = argparse.ArgumentParser(prog='quota-reset', description=__doc__)
    parser.add_argument('--list', action='store_true', help='list rules and reset commands')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--provider', help='select every enabled rule for this provider')
    selection.add_argument('--rule', action='append', help='exact rule name; repeat to reset several together')
    parser.add_argument('--apply', action='store_true', help='clear selected usage (default: preview)')
    args = parser.parse_args(argv)
    if args.list and args.apply:
        parser.error('--list cannot be combined with --apply')
    if not args.list and not (args.rule or args.provider):
        parser.error('select --provider or --rule, or use --list')
    return args


def main():
    def interrupted(signum, frame):
        raise InterruptedError('quota reset interrupted; check quota-status before retrying')
    signal.signal(signal.SIGTERM, interrupted)
    args = parse_args()
    if os.geteuid() != 0:
        raise ValueError('run with sudo')
    import yaml
    root = Path(os.environ.get('PRAXIS_CONFIG_DIR', '/etc/praxis'))
    config = yaml.safe_load((root / 'shared-gateway.yaml').read_text())
    if args.list:
        for row in listing(config, provider=args.provider, names=args.rule)['rules']:
            try:
                selected_rules(config, names=[row['rule']])
            except ValueError as error:
                print(str(error))
            else:
                print('sudo scripts/common/quota-reset --rule ' + shlex.quote(row['rule']))
        print('Commands preview only. Append --apply to reset; repeat --rule to select multiple budgets.')
        return
    reset(config, provider=args.provider, names=args.rule, apply=args.apply)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'error: {error}') from None
