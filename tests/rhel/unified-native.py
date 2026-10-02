#!/usr/bin/env python3
"""Run file/tool tasks with the ordinary user's installed unified configs."""
import argparse
import json
import os
from pathlib import Path
import pwd
import time

import integration


def qualify(name, model, environment=None, api='openai'):
    account = pwd.getpwnam(integration.USER)
    directory = Path(account.pw_dir) / 'rhel-smoke' / ('unified-' + name + '-' + str(time.time_ns()))
    directory.mkdir(parents=True, mode=0o700)
    os.chown(directory, account.pw_uid, account.pw_gid)
    assert integration.user_command('git', 'init', '-q', directory).returncode == 0
    env = dict(environment or {})
    if name == 'codex':
        command = ['codex', '--profile', 'praxis', 'exec', '--json', '--ephemeral',
                   '--sandbox', 'workspace-write', '-c', 'approval_policy="never"', '--model', model]
    elif name == 'claude':
        command = ['claude-code', '-p', '--verbose', '--output-format', 'stream-json',
                   '--max-turns', '12', '--model', model, '--effort', 'medium',
                   '--permission-mode', 'default', '--allowedTools', 'Read', 'Write', 'Edit', 'Bash(python3 *)', '--']
    else:
        provider = 'praxis-messages' if api == 'anthropic' else 'praxis-openai'
        command = ['opencode', 'run', '--format', 'json', '--model', provider + '/' + model, '--thinking']
        env['OPENCODE_CONFIG_CONTENT'] = json.dumps({'agent': {'build': {'steps': 12}},
            'permission': {'*': 'deny', 'read': 'allow', 'edit': 'allow', 'bash': {'*': 'deny', 'python3 *': 'allow'}}})
    started = time.monotonic()
    result = integration.user_command(*command, integration.TASK, directory=directory,
                                      environment=env, timeout=600)
    output = result.stdout + result.stderr
    log = directory / 'harness.log'
    log.write_text(output)
    log.chmod(0o600)
    assert result.returncode == 0, (name, result.returncode, str(log))
    assert (directory / 'add.py').is_file() and (directory / 'test_add.py').is_file(), (name, 'no files', str(log))
    assert integration.ran_tests(name, output), (name, 'no successful unittest tool event', str(log))
    checked = integration.user_command('python3', '-m', 'unittest', '-v', directory=directory)
    assert checked.returncode == 0 and 'Ran 0 tests' not in checked.stderr, (name, 'independent tests failed')
    assert integration.user_command('python3', '-c',
        'from add import add; assert add(2,3)==5; assert add(-2,-3)==-5; assert add(0,0)==0',
        directory=directory).returncode == 0
    print(f'PASS {name}: {model}: files, successful tool event and independent tests '
          f'({time.monotonic() - started:.1f}s); {directory}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--harness', choices=('codex', 'claude', 'opencode'))
    args = parser.parse_args()
    if os.geteuid() != 0 or not args.model.startswith('vllm/'):
        parser.error('run as admin against an explicit local vllm/ model; cloud calls are manual')
    account = pwd.getpwnam(args.user)
    if account.pw_uid < 1000 or account.pw_gid == 0:
        parser.error('select an ordinary user')
    integration.USER = args.user
    failures = []
    for name in ([args.harness] if args.harness else ('codex', 'claude', 'opencode')):
        print('RUN ' + name + ': ' + args.model, flush=True)
        try:
            qualify(name, args.model)
        except Exception as error:
            failures.append(name)
            print('FAIL ' + str(error), flush=True)
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
