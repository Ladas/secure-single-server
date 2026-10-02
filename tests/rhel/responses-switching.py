#!/usr/bin/env python3
"""Local qualification driver: real native CLIs, synthetic projects, existing gateway."""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import pwd
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import integration
ACCOUNT = None
ROOT = None
RESULTS = []
LOCK = threading.Lock()
GPU = threading.Lock()
PORT = None


def save(row):
    with LOCK:
        RESULTS.append(row)
        (ROOT / 'results.json').write_text(json.dumps(RESULTS, indent=2) + '\n')
        print(json.dumps(row), flush=True)


def events(output):
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            yield event


def reply(name, output):
    text = []
    for e in events(output):
        if name == 'codex' and e.get('type') == 'item.completed':
            i = e.get('item', {})
            if i.get('type') == 'agent_message':
                text.append(i.get('text', ''))
        elif name == 'opencode' and e.get('type') == 'text':
            text.append(e.get('part', {}).get('text', ''))
    return '\n'.join(text)


def problem(output):
    # Report only a classification. Full synthetic test output stays private in the project log.
    for needle, label in [('Encrypted content is not supported', 'vllm-encrypted-reasoning'),
                          ('validation errors', 'input-schema-validation'),
                          ('array_above_max_length', 'plaintext-reasoning-replay'),
                          ('rate_limit', 'rate-limit'), ('429', 'rate-limit'),
                          ('model_not_found', 'model-not-found'), ('context_length', 'context-limit'),
                          ('signature', 'signature-error')]:
        if needle in output:
            return label
    return 'inspect-log'


class Conversation:
    def __init__(self, name, label):
        self.name = name
        self.directory = ROOT / (name + '-' + label + '-' + secrets.token_hex(3))
        self.directory.mkdir(mode=0o700)
        os.chown(self.directory, ACCOUNT.pw_uid, ACCOUNT.pw_gid)
        for filename, source in [('add.py', 'def add(a, b):\n    return a + b\n'),
                                 ('test_add.py', 'import unittest\nfrom add import add\nclass TestAdd(unittest.TestCase):\n    def test_values(self):\n        self.assertEqual(add(2, 3), 5)\n        self.assertEqual(add(-2, -3), -5)\n        self.assertEqual(add(0, 0), 0)\n')]:
            path = self.directory / filename
            path.write_text(source)
            os.chown(path, ACCOUNT.pw_uid, ACCOUNT.pw_gid)
        assert integration.user_command('git', 'init', '-q', self.directory).returncode == 0
        self.marker = 'history-' + secrets.token_hex(6)
        self.session = None
        self.turn = 0
        self.previous = None

    def call(self, target):
        api, model = target
        if self.session is None:
            prompt = ('Remember this conversation-only marker: ' + self.marker + '. Do not save it to a file. '
                      'Run python3 -m unittest -v using the shell tool in this project. '
                      'Then reply with the marker and test result in one line. Do not read credentials, '
                      'other projects, configuration or session files. Do not use subagents or network tools.')
        else:
            prompt = ('Recall the conversation-only marker from the first turn. Run python3 -m unittest -v '
                      'using the shell tool, then reply with that marker and test result in one line. '
                      'Do not read session files or other projects. Do not change configuration, access credentials, '
                      'use network tools or subagents. Do not save the marker to a file.')
        env = {}
        if self.name == 'codex':
            cmd = ['codex', '--profile', 'praxis', '-c', 'approval_policy="never"',
                   '-c', 'sandbox_mode="workspace-write"',
                   '-c', 'model_providers.praxis.base_url="http://127.0.0.1:' + str(PORT) + '/v1"', 'exec']
            if self.session:
                cmd += ['resume', self.session]
            cmd += ['--json', '--model', model, prompt]
        else:
            prefix = 'praxis-messages/' if api == 'anthropic' else 'praxis-openai/'
            cmd = ['opencode', 'run', '--format', 'json', '--model', prefix + model, '--thinking']
            if self.session:
                cmd += ['--session', self.session]
            cmd += [prompt]
            env['OPENCODE_CONFIG_CONTENT'] = json.dumps({'provider': {'praxis-openai': {'options': {
                'baseURL': 'http://127.0.0.1:' + str(PORT) + '/v1'}}}, 'agent': {'build': {'steps': 5}},
                'permission': {'*': 'deny', 'read': 'allow', 'bash': {'*': 'deny', 'python3 *': 'allow'}}})
        log = self.directory / ('turn-' + str(self.turn) + '.jsonl')
        started = time.monotonic()
        try:
            if model.startswith('vllm/'):
                GPU.acquire()
            try:
                result = integration.user_command(*cmd, directory=self.directory, environment=env, timeout=240)
                output = result.stdout + result.stderr
                code = result.returncode
            finally:
                if model.startswith('vllm/'):
                    GPU.release()
        except subprocess.TimeoutExpired as error:
            output = (error.stdout or '') + (error.stderr or '')
            code = 124
        log.write_text(output)
        log.chmod(0o600)
        for e in events(output):
            if self.name == 'codex' and e.get('type') == 'thread.started':
                self.session = e.get('thread_id')
            elif self.name == 'opencode' and e.get('sessionID'):
                self.session = e['sessionID']
        recalled = self.marker in reply(self.name, output)
        tool = integration.ran_tests(self.name, output)
        errors = [e for e in events(output) if e.get('type') in ('error', 'turn.failed') or e.get('is_error')]
        passed = code == 0 and recalled and tool and not errors and self.session is not None
        row = {'harness': self.name, 'from': self.previous, 'to': target,
               'status': 'PASS' if passed else 'FAIL', 'recall': recalled, 'tool': tool,
               'seconds': round(time.monotonic() - started, 1), 'log': str(log),
               'session': self.session}
        if not passed:
            row.update(reason='timeout' if code == 124 else problem(output), returncode=code)
        save(row)
        self.previous = target
        self.turn += 1
        return passed


def chain(name, targets):
    conversation = Conversation(name, 'compat')
    for target in targets:
        if not conversation.call(target):
            return False
    return True


def main():
    global ACCOUNT, ROOT, PORT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user', required=True, help='Existing ordinary harness account')
    parser.add_argument('--local-model', required=True)
    parser.add_argument('--cloud-model', action='append', required=True)
    parser.add_argument('--messages-model', action='append', default=[])
    parser.add_argument('--port', type=int, default=18180)
    parser.add_argument('--upstream-port', type=int, default=8080)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('run with sudo; harnesses and adapter run as --user')
    integration.USER = args.user
    ACCOUNT = pwd.getpwnam(args.user)
    if ACCOUNT.pw_uid == 0:
        parser.error('harness user must not be root')
    PORT = args.port
    ROOT = Path(ACCOUNT.pw_dir) / 'rhel-smoke' / ('responses-compat-' + str(time.time_ns()))
    ROOT.mkdir(mode=0o700)
    os.chown(ROOT, ACCOUNT.pw_uid, ACCOUNT.pw_gid)
    # The ordinary user cannot traverse the administrator's deployment directory.
    adapter_source = ROOT / 'responses_compat.py'
    adapter_source.write_bytes(Path(__file__).with_name('responses_compat.py').read_bytes())
    adapter_source.chmod(0o644)
    adapter_log = ROOT / 'adapter.jsonl'
    with adapter_log.open('w') as log:
        adapter_log.chmod(0o600)
        adapter = subprocess.Popen(['runuser', '-u', args.user, '--', 'python3', '-B',
            str(adapter_source), '--port', str(PORT),
            '--upstream-port', str(args.upstream_port), '--model', args.local_model],
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            for attempt in range(50):
                if adapter.poll() is not None:
                    raise RuntimeError('adapter failed to start; inspect its private log')
                if adapter_log.read_text().startswith('Responses compatibility experiment listening'):
                    with socket.create_connection(('127.0.0.1', PORT), timeout=0.2):
                        break
                time.sleep(0.1)
            else:
                raise RuntimeError('adapter did not become ready')
            print('EVIDENCE ' + str(ROOT), flush=True)
            local = ('openai', args.local_model)
            targets = [local]
            for model in args.cloud_model:
                targets += [('openai', model), local]
            opencode_targets = list(targets)
            for model in args.messages_model:
                opencode_targets += [('anthropic', model), local]
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(chain, 'codex', targets),
                           pool.submit(chain, 'opencode', opencode_targets)]
                passed = all([future.result() for future in futures])
            print('COMPLETE ' + str(ROOT), flush=True)
            return 0 if passed else 1
        finally:
            if adapter.poll() is None:
                os.killpg(adapter.pid, signal.SIGTERM)
            try:
                adapter.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(adapter.pid, signal.SIGKILL)
                adapter.wait()


if __name__ == '__main__':
    raise SystemExit(main())
