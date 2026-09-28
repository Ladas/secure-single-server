#!/usr/bin/env python3
"""Run the pinned Praxis image against a synthetic OpenAI server on Linux.

Use host networking so the shipped profile is tested unchanged, including its
loopback-only listeners and upstream. No weights, GPUs or provider keys needed.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]
ENGINE = os.environ.get('CONTAINER_ENGINE', 'podman')
MODEL = 'Qwen/Qwen3-8B'
sys.path.insert(0, str(ROOT / 'tests/common'))
from provider import Provider
from contracts import check
from evidence import save


def run(*args):
    return subprocess.check_output(list(map(str, args)), text=True).strip()


def main():
    image = run('bash', '-c', 'source "$1/scripts/common/lib.sh"; printf "%s" "$DEFAULT_PRAXIS_IMAGE"',
                'test', ROOT)
    run('bash', '-c', 'source "$1/scripts/common/lib.sh"; check_native_image "$2" "$3"',
        'test', ROOT, ENGINE, image)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(path, body=None):
        req = urllib.request.Request('http://127.0.0.1:8080' + path,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json',
                                              'Authorization': 'Bearer must-not-reach-vllm',
                                              'X-Model': 'spoofed', 'X-Cluster': 'cloud'})
        with opener.open(req, timeout=10) as response:
            return response.headers, response.read().decode()

    name = 'sss-local-inference-' + uuid.uuid4().hex[:12]
    server = Provider(ports=(8000, 0, 0), openai_authorization=None, model=MODEL)
    server.start()
    result = {'status': 'failed', 'profile': 'local-vllm', 'runtime': 'not run'}
    try:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'praxis.yaml'
            config.write_bytes((ROOT / 'configs/vllm/praxis.yaml').read_bytes())
            config.chmod(0o644)
            args = [ENGINE, 'run', '-d', '--name', name, '--network=host', '--read-only',
                    '--cap-drop=all', '--security-opt=no-new-privileges', '--user=1001:1001']
            if Path(ENGINE).name == 'podman':
                args += ['--userns=keep-id:uid=1001,gid=1001']
            run(*args, '-v', f'{config}:/etc/praxis/local.yaml:ro,Z', image,
                '-c', '/etc/praxis/local.yaml')
            for attempt in range(60):
                try:
                    _, body = request('/v1/models')
                    break
                except (OSError, urllib.error.URLError):
                    if attempt == 59:
                        raise
                    time.sleep(1)
            assert json.loads(body)['data'][0]['id'] == MODEL, body
            payload = {'model': MODEL, 'messages': [{'role': 'user', 'content': 'hello'}], 'max_tokens': 16}
            _, body = request('/v1/chat/completions', payload)
            check('/v1/chat/completions', body, model=MODEL)
            payload = {**payload, 'stream': True, 'tools': [{'type': 'function', 'function': {
                'name': 'add', 'parameters': {'type': 'object', 'properties': {
                    'a': {'type': 'integer'}, 'b': {'type': 'integer'}}}}}]}
            headers, body = request('/v1/chat/completions', payload)
            assert headers.get_content_type() == 'text/event-stream', headers
            check('/v1/chat/completions', body, stream=True, tool=True, model=MODEL)
            records = server.records
            assert records[-1]['model'] == MODEL and records[-1]['stream'], records
            assert all(record['credential_ok'] and record['classification_clean'] for record in records), records
            assert all(record['model'] == MODEL for record in records if record['method'] == 'POST'), records
            server.close()
            time.sleep(1)  # replenish the profile's request-rate budget
            try:
                request('/v1/chat/completions', payload)
            except urllib.error.HTTPError as error:
                assert error.code == 502, error.code
            else:
                raise AssertionError('unavailable local backend did not fail closed')
            result['status'] = 'passed'
            result['records'] = records
            print('Local Praxis: models, chat, SSE tool calls, header stripping and backend failure passed')
    finally:
        server.close()
        save("local-vllm", result)
        subprocess.run([ENGINE, 'logs', name], check=False)
        subprocess.run([ENGINE, 'rm', '-f', name], check=False)


if __name__ == '__main__':
    if not __debug__ or os.environ.get('PYTHONOPTIMIZE'):
        raise SystemExit('Run tests without Python -O/PYTHONOPTIMIZE')
    main()
