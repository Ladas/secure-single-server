#!/usr/bin/env python3
"""Run the pinned Praxis image against a synthetic OpenAI server on Linux.

Use host networking so the shipped profile is tested unchanged, including its
loopback-only listeners and upstream. No weights, GPUs or provider keys needed.
"""
import http.server
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]
ENGINE = os.environ.get('CONTAINER_ENGINE', 'podman')
MODEL = 'Qwen/Qwen3-8B'
TOOL = {'index': 0, 'id': 'call_test', 'type': 'function',
        'function': {'name': 'bash', 'arguments': '{"command":"echo hello"}'}}
SEEN = []


class Provider(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        SEEN.append((self.path, dict(self.headers), None))
        self.send_body({'object': 'list', 'data': [{'id': MODEL, 'object': 'model'}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        SEEN.append((self.path, dict(self.headers), body))
        if body.get('stream'):
            chunk = {'id': 'test', 'object': 'chat.completion.chunk', 'model': MODEL,
                     'choices': [{'index': 0, 'delta': {'tool_calls': [TOOL]}, 'finish_reason': None}]}
            end = {'id': 'test', 'object': 'chat.completion.chunk', 'model': MODEL,
                   'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls'}],
                   'usage': {'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 5}}
            self.send_body('data: ' + json.dumps(chunk) + '\n\ndata: ' + json.dumps(end) +
                           '\n\ndata: [DONE]\n\n', 'text/event-stream')
        else:
            self.send_body({'id': 'test', 'object': 'chat.completion', 'model': MODEL,
                            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'hello'},
                                         'finish_reason': 'stop'}],
                            'usage': {'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 5}})

    def send_body(self, body, content_type='application/json'):
        data = (json.dumps(body) if isinstance(body, dict) else body).encode()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


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
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 8000), Provider)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
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
            assert json.loads(body)['choices'][0]['message']['content'] == 'hello', body
            payload = {**payload, 'stream': True, 'tools': [{'type': 'function', 'function': {
                'name': 'bash', 'parameters': {'type': 'object', 'properties': {'command': {'type': 'string'}}}}}]}
            headers, body = request('/v1/chat/completions', payload)
            assert headers.get_content_type() == 'text/event-stream', headers
            events = [line[6:] for line in body.splitlines() if line.startswith('data: ')]
            assert events[-1] == '[DONE]', body
            assert json.loads(events[0])['choices'][0]['delta']['tool_calls'] == [TOOL], body
            assert SEEN[-1][2] == payload, SEEN
            for path, headers, _ in SEEN:
                lowered = {key.lower(): value for key, value in headers.items()}
                assert path in ('/v1/models', '/v1/chat/completions'), path
                assert not {'authorization', 'x-model', 'x-cluster'} & lowered.keys(), headers
            server.shutdown()
            server.server_close()
            time.sleep(1)  # replenish the profile's request-rate budget
            try:
                request('/v1/chat/completions', payload)
            except urllib.error.HTTPError as error:
                assert error.code == 502, error.code
            else:
                raise AssertionError('unavailable local backend did not fail closed')
            print('Local Praxis: models, chat, SSE tool calls, header stripping and backend failure passed')
    finally:
        server.shutdown()
        server.server_close()
        subprocess.run([ENGINE, 'logs', name], check=False)
        subprocess.run([ENGINE, 'rm', '-f', name], check=False)


if __name__ == '__main__':
    main()
