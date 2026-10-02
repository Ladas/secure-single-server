#!/usr/bin/env python3
"""Pinned Praxis unified routing against private, credential-checking providers."""
import json
import importlib.util
from pathlib import Path
import sys
import time
from unittest.mock import patch
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'scripts/common'), str(ROOT / 'tests/common')]
from gateway import ENGINE, Gateway, run, request_body
from contracts import check
from test_unified import MODELS, CUSTOM
from provider_config import render
import quota_status
import quota_reset

spec = importlib.util.spec_from_file_location('provider_image', Path(__file__).with_name('provider-image.py'))
provider_image = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provider_image)


class UnifiedGateway(Gateway):
    harnesses = False
    hide_vllm_reasoning = True

    def fixture_code(self):
        if not self.harnesses:
            return ''
        source = Path(__file__).with_name('harness_provider.py').read_text()
        return ('import provider; ns={"__name__":"fixture", "__file__":"/tests/rhel/harness_provider.py"}; '
                'exec(' + repr(source) + ',ns); provider.completion=ns["completion"]; '
                'provider.continuation=ns["continuation"]; ')

    def boot(self):
        if not hasattr(self, 'unified'):
            self.unified = True
            run(ENGINE, 'exec', '--detach', self.name + '-mock', 'python3', '-c',
                self.fixture_code() + 'from provider import Provider; import threading; '
                'p=Provider(ports=(8000,8001,19001),model="qwen3-8b",local=True); '
                'p.start(); threading.Event().wait()')
            run(ENGINE, 'exec', '--detach', self.name + '-mock', 'python3', '-c',
                self.fixture_code() + 'from provider import Provider; import threading; '
                'p=Provider(ports=(18082,18083,19002),openai_authorization="Bearer synthetic-anthropic",strict_openai=True); '
                'p.start(); threading.Event().wait()')
            if self.harnesses:
                run(ENGINE, 'exec', '--detach', self.name + '-mock', 'python3', '-c',
                    self.fixture_code() + 'from provider import Provider; import threading; '
                    'p=Provider(ports=(18084,18085,19003),strict_openai=True); p.start(); threading.Event().wait()')
            for chain in self.config['filter_chains']:
                for item in chain['filters']:
                    if item['filter'] == 'token_rate_limit':
                        item['rules'][0]['capacity'] = 10000
            self.config = render(self.config, vllm=True, openai=True, anthropic=False,
                                 custom=CUSTOM, shared_vllm=True, models=MODELS,
                                 hide_vllm_reasoning=self.hide_vllm_reasoning)
            for chain in self.config['filter_chains']:
                for item in chain['filters']:
                    if item['filter'] == 'load_balancer':
                        for cluster in item['clusters']:
                            if cluster['name'] == 'vllm':
                                cluster['endpoints'] = ['127.0.0.1:8000']
                            elif cluster['name'] == 'openai' and self.harnesses:
                                cluster['endpoints'] = ['127.0.0.1:18084']
                            elif cluster['name'].startswith('team-'):
                                cluster['endpoints'] = ['127.0.0.1:18082' if cluster['name'] == 'team-openai' else '127.0.0.1:18083']
                                cluster.pop('tls', None)
                                cluster['http'].pop('authority', None)
            self.arguments += ['-e', 'CUSTOM_TEAM_API_KEY=synthetic-anthropic']
        (self.work / 'gateway.json').write_text(json.dumps(self.config))
        try:
            super().boot()
        except Exception:
            print(run(ENGINE, 'logs', self.name), flush=True)
            raise

    def raw(self, path, raw, **extra):
        time.sleep(.55)
        port = self.anthropic_port if path.startswith('/v1/messages') else self.openai_port
        headers = {'Content-Type': 'application/json', **extra}
        request = urllib.request.Request('http://127.0.0.1:' + port + path,
                                         data=raw, headers=headers)
        try:
            response = self.opener.open(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.read()


def exercise(gateway):
    for api, port in [('openai', gateway.openai_port), ('anthropic', gateway.anthropic_port)]:
        with gateway.opener.open('http://127.0.0.1:' + port + '/v1/models') as response:
            found = json.load(response)
        assert [m['id'] for m in found['data']] == [m['id'] for m in MODELS if api in m['apis']]
    for model in MODELS:
        for api in model['apis']:
            paths = ['/v1/messages'] if api == 'anthropic' else ['/v1/responses', '/v1/chat/completions']
            for path in paths:
                for stream in (False, True):
                    body = request_body(path, stream, tools=True)
                    body['model'] = model['id']
                    if path == '/v1/chat/completions' and model['model'].startswith('gpt-'):
                        body['max_completion_tokens'] = body.pop('max_tokens')
                    status, payload, _ = gateway.request(path, body=body)
                    assert status == 200, (model['id'], path, stream, status, payload[:300])
                    check(path, payload, stream, tool=True, model=model['model'])
    print('PASS: both catalogs, provider aliases, native APIs, streaming and tools', flush=True)
    before = provider_image.balances(gateway)
    assert before == {'vllm-rolling-day': 30, 'openai-rolling-day': 20,
                      'team-openai-rolling-day': 20, 'team-anthropic-rolling-day': 10}, before
    for path in ('/v1/responses', '/v1/chat/completions', '/v1/messages'):
        for body in (b'{"model":"vllm/qwen3-8b", bad', b'{}', b'{"model":"unknown"}',
                     b'{"model":"vllm/qwen3-8b"} trailing'):
            status, payload = gateway.raw(path, body, **{
                'X-Gateway-Model': 'openai/gpt-5.4-mini', 'X-Gateway-Provider': 'openai'})
            assert status in (400, 404), (path, body, status, payload[:300])
    print('PASS: invalid/unknown models cannot select a provider with forged headers', flush=True)
    assert provider_image.balances(gateway) == before, 'rejected models consumed provider quota'
    for path in ('/providers/team/v1/responses', '/vllm/v1/responses', '/v1/unknown'):
        assert gateway.raw(path, b'{"model":"vllm/qwen3-8b"}')[0] == 404
    body = {**request_body('/v1/responses'), 'model': 'vllm/qwen3-8b'}
    assert gateway.raw('/v1/responses', json.dumps(body).encode(), **{
        'X-Gateway-Model': 'openai/gpt-5.4-mini', 'X-Gateway-Provider': 'openai'})[0] == 200
    before['vllm-rolling-day'] += 5
    assert provider_image.balances(gateway) == before, 'forged headers selected the wrong quota'
    print('PASS: one shared vLLM charge across APIs; independent cloud budgets; no legacy routes', flush=True)

    def stopped(*args):
        assert args == ('systemctl', '--user', 'stop', 'praxis.service')
        run(ENGINE, 'stop', gateway.name)

    def restart():
        run(ENGINE, 'start', gateway.name)
        gateway.ready()

    with patch.object(quota_status, 'service', provider_image.service_adapter(gateway)), \
            patch.object(quota_reset.provider_manage, 'service', stopped), \
            patch.object(quota_reset.provider_manage, 'restart', restart):
        quota_reset.reset(gateway.config, names=['openai-rolling-day'], apply=True)
        before['openai-rolling-day'] = 0
        assert provider_image.balances(gateway) == before
        quota_reset.reset(gateway.config, provider='team', apply=True)
        before.update({'team-openai-rolling-day': 0, 'team-anthropic-rolling-day': 0})
        assert provider_image.balances(gateway) == before
    assert gateway.request('/v1/responses', body=body)[0] == 200
    before['vllm-rolling-day'] += 5
    assert provider_image.balances(gateway) == before
    print('PASS: single and multiple quota resets, unrelated usage retained, inference after restart', flush=True)
    history_contract(gateway)
    for port in (19000, 19001, 19002):
        records = json.loads(run(ENGINE, 'exec', gateway.name + '-mock', 'python3', '-c',
            'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:' + str(port) +
            '/state").read().decode())'))['records']
        for record in records:
            expected = False if port == 19001 and record['path'] == '/v1/responses' else None
            assert record.get('include_reasoning') is expected, (port, record)
    print('PASS: reasoning suppression affects only local vLLM Responses; cloud/Chat/Messages unchanged', flush=True)


def history_contract(gateway):
    """Reproduce the known cross-backend gap without reading a user's session."""
    history = [
        {'role': 'user', 'content': 'Add two and three.'},
        {'type': 'reasoning', 'id': 'rs_local', 'summary': [],
         'content': [{'type': 'reasoning_text', 'text': 'Synthetic local reasoning.'}]},
        {'type': 'function_call', 'call_id': 'call_fixture', 'name': 'add', 'arguments': '{"a":2,"b":3}'},
        {'type': 'function_call_output', 'call_id': 'call_fixture', 'output': '5'},
        {'role': 'assistant', 'content': [{'type': 'output_text', 'text': '5'}]},
        {'role': 'user', 'content': 'Continue with this history.'},
    ]
    body = {'model': 'vllm/qwen3-8b', 'input': history, 'store': False}
    assert gateway.request('/v1/responses', body=body)[0] == 200
    body['model'] = 'team/gpt-5.4-mini'
    status, payload, _ = gateway.request('/v1/responses', body=body)
    assert status == 400
    assert json.loads(payload)['error']['param'] == 'input[1].content'
    # Control only: manually remove the incompatible item in the synthetic
    # request. No gateway/history normalizer is implemented by this test.
    body['input'] = [item for item in history if item.get('type') != 'reasoning']
    assert gateway.request('/v1/responses', body=body)[0] == 200
    print('KNOWN GAP reproduced: local reasoning history rejected by cloud; '
          'messages and paired tools accepted when that reasoning item is omitted', flush=True)


if __name__ == '__main__':
    with UnifiedGateway('all-in-one', 'valkey') as gateway:
        exercise(gateway)
