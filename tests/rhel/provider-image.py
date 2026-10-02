#!/usr/bin/env python3
"""Real pinned Praxis with local vLLM and independent cloud-provider fixtures."""
import argparse
import copy
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tests/common"), str(ROOT / "scripts/common")]
from gateway import ENGINE, Gateway, run, request_body
from contracts import check
from provider_config import render
import quota_config
import quota_status
import quota_share
from quota_manage import plan as quota_plan


class ProvidersGateway(Gateway):
    openai = False
    anthropic = False
    quota_overrides = None
    shared_vllm = False
    custom = None

    def boot(self):
        # One fixture namespace, with no host publication of any upstream port.
        if not hasattr(self, "baseline"):
            self.baseline = copy.deepcopy(self.config)
            for chain in self.baseline["filter_chains"]:
                for f in chain["filters"]:
                    if f["filter"] == "token_rate_limit":
                        f["rules"][0]["capacity"] = 10000
            run(ENGINE, "exec", "--detach", self.name + "-mock", "python3", "-c",
                'from provider import Provider; import threading; '
                'p=Provider(ports=(8000,8001,19001),model="qwen3-8b",local=True); '
                'p.start(); threading.Event().wait()')
        self.config = render(self.baseline, vllm=True, openai=self.openai, anthropic=self.anthropic,
                             shared_vllm=self.shared_vllm, custom=self.custom)
        self.config = quota_config.apply(self.config, self.quota_overrides or {})
        for chain in self.config["filter_chains"]:
            for f in chain["filters"]:
                if f["filter"] == "load_balancer":
                    for cluster in f["clusters"]:
                        if cluster["name"] == "vllm":
                            cluster["endpoints"] = ["127.0.0.1:8000"]
                        elif cluster['name'].startswith('team-'):
                            cluster['endpoints'] = ['127.0.0.1:18082' if cluster['name'] == 'team-openai' else '127.0.0.1:18083']
                            cluster.pop('tls', None)
                            cluster.pop('http', None)
        (self.work / "gateway.json").write_text(json.dumps(self.config))
        # Qwen-only really starts without either cloud credential in the process.
        for variable, enabled in (("OPENAI_API_KEY=synthetic-openai", self.openai),
                                  ("ANTHROPIC_API_KEY=synthetic-anthropic", self.anthropic)):
            if variable in self.arguments:
                i = self.arguments.index(variable)
                del self.arguments[i-1:i+1]
            if enabled:
                self.arguments += ["-e", variable]
        super().boot()

    def change(self, openai, anthropic):
        run(ENGINE, "rm", "--force", self.name)
        self.openai, self.anthropic = openai, anthropic
        try:
            self.boot()
        except Exception:
            print(run(ENGINE, 'logs', self.name), flush=True)
            raise

    def request(self, path, **kwargs):
        # Gateway.request selects the Messages listener from the unprefixed path.
        old = self.openai_port
        if path.startswith(("/vllm/v1/messages", "/providers/team/v1/messages")):
            self.openai_port = self.anthropic_port
        try:
            return super().request(path, **kwargs)
        finally:
            self.openai_port = old


def exercise(gateway):
    for openai, anthropic in ((False, False), (True, False), (True, True), (False, True)):
        if (gateway.openai, gateway.anthropic) != (openai, anthropic):
            gateway.change(openai, anthropic)
        old_port = gateway.openai_port
        if gateway.scenario == "all-in-one":
            gateway.openai_port = gateway.anthropic_port
        try:
            status, payload, _ = gateway.request("/vllm/v1/models?limit=1000", method="GET")
            assert status == 200 and json.loads(payload)["data"][0]["id"] == "qwen3-8b"
            status, _, _ = gateway.request("/v1/models?limit=1000", method="GET")
            enabled = (openai or anthropic) if gateway.scenario == "remote" else anthropic
            assert status == (200 if enabled else 404), ("model discovery", status)
        finally:
            gateway.openai_port = old_port
        for path in ("/v1/responses", "/v1/chat/completions", "/v1/messages"):
            for stream in (False, True):
                body = request_body(path, stream, tools=True)
                body["model"] = "qwen3-8b"
                status, payload, _ = gateway.request("/vllm" + path, body=body)
                assert status == 200, (path, status, payload[:400])
                check(path, payload, stream, tool=True, model="qwen3-8b")
            enabled = anthropic if path == "/v1/messages" else openai
            status, payload, _ = gateway.request(path, body=request_body(path))
            assert status == (200 if enabled else 404), (path, status, payload[:400])
        before = len(gateway.records())
        status, _, _ = gateway.request("/vllm/v1/chat/completions", body={"model": "unknown", "messages": []})
        assert status == 404 and len(gateway.records()) == before, "unknown local model fell back to cloud"
        if gateway.scenario == "remote":
            status, _, _ = gateway.request("/vllm/v1/models", method="GET", bearer="invalid")
            assert status == 401, "local model path bypassed JWT"
        print(f"PASS {gateway.scenario}/{gateway.profile}: Qwen + OpenAI={openai}, Anthropic={anthropic}", flush=True)


def exercise_capacities(gateway):
    path = "/vllm/v1/responses"
    body = request_body("/v1/responses")
    body["model"] = "qwen3-8b"

    def capacity(value):
        gateway.quota_overrides, _ = quota_plan(gateway.config, gateway.quota_overrides or {},
                                               value, provider="vllm")
        gateway.change(gateway.openai, gateway.anthropic)

    def persisted_charge(expected):
        if gateway.profile != "valkey":
            return

        def service(*args, input_text=None):
            if args[:2] == ("podman", "inspect"):
                return json.dumps(run(ENGINE, "inspect", gateway.name, "--format", "{{.Config.Image}}"))
            args = [ENGINE, *args[1:]]
            args = [gateway.name if arg == "praxis-shared-gateway" else
                    gateway.name + "-valkey" if arg == "praxis-valkey" else arg for arg in args]
            return subprocess.run(args, input=input_text, text=True, capture_output=True,
                                  check=True, timeout=15).stdout

        for _ in range(20):
            now = datetime.now(timezone.utc)
            rows = quota_status.summarize(gateway.config, "", now, now, now)
            with patch.object(quota_status, "service", service):
                quota_status.read_valkey_balances(gateway.config, rows)
            row = next(row for row in rows if row["rule"] == "vllm-openai-rolling-day")
            if row["charged"] == expected:
                assert row["basis"] == "valkey ledger"
                assert row["remaining"] == max(0, row["capacity"] - expected)
                assert row["actual"] is None, "ledger must not invent post-restart metrics"
                return
            time.sleep(0.1)
        raise AssertionError(("persisted quota display", expected, rows))

    capacity(20)
    persisted_charge(0)
    for _ in range(3):
        status, payload, _ = gateway.request(path, body=body)
        assert status == 200, (status, payload[:400])
    assert gateway.request(path, body=body)[0] == 429, "small capacity was not enforced"
    persisted_charge(15)
    capacity(100)
    assert gateway.request(path, body=body)[0] == 200, "increase did not restore admission"
    persisted_charge(20)
    capacity(20)
    expected = 429 if gateway.profile == "valkey" else 200
    assert gateway.request(path, body=body)[0] == expected, "unexpected restart accounting"
    persisted_charge(20)
    # Restore room for the provider matrix, retaining explicit overrides.
    capacity(10000)
    print(f"PASS {gateway.scenario}/{gateway.profile}: quota decrease, increase and restart accounting", flush=True)


def service_adapter(gateway):
    def service(*args, input_text=None):
        if args[:2] == ('podman', 'inspect'):
            return json.dumps(run(ENGINE, 'inspect', gateway.name, '--format', '{{.Config.Image}}'))
        args = [ENGINE, *args[1:]]
        args = [gateway.name if arg == 'praxis-shared-gateway' else
                gateway.name + '-valkey' if arg == 'praxis-valkey' else arg for arg in args]
        return subprocess.run(args, input=input_text, text=True, capture_output=True, check=True, timeout=15).stdout
    return service


def balances(gateway):
    now = datetime.now(timezone.utc)
    rows = quota_status.summarize(gateway.config, '', now, now, now)
    with patch.object(quota_status, 'service', service_adapter(gateway)):
        quota_status.read_valkey_balances(gateway.config, rows)
    return {row['rule']: row['charged'] for row in rows}


def exercise_extended(gateway):
    for path in ('/v1/responses', '/v1/messages'):
        body = {**request_body(path), 'model': 'qwen3-8b'}
        assert gateway.request('/vllm' + path, body=body)[0] == 200
    time.sleep(.5)
    assert sum(balances(gateway).values()) == 10
    # Run the real migration using the pinned image and ACL, with Praxis stopped.
    with patch.object(quota_status, 'service', service_adapter(gateway)):
        migrate = quota_share.prepare(gateway.config)
        run(ENGINE, 'stop', gateway.name)
        migrate()
        try:
            migrate()
        except (ValueError, subprocess.CalledProcessError):
            pass
        else:
            raise AssertionError('migration overwrote an existing ledger')
    gateway.shared_vllm = True
    gateway.quota_overrides = {'vllm-rolling-day': 15}
    gateway.change(True, True)
    assert balances(gateway)['vllm-rolling-day'] == 10
    for path in ('/v1/responses', '/v1/messages'):
        body = {**request_body(path), 'model': 'qwen3-8b'}
        assert gateway.request('/vllm' + path, body=body)[0] == 429, path
        assert gateway.request(path, body=request_body(path))[0] == 200, 'cloud budget was affected'
    gateway.quota_overrides['vllm-rolling-day'] = 100
    gateway.change(True, True)
    for path in ('/v1/responses', '/v1/messages'):
        assert gateway.request('/vllm' + path, body={**request_body(path), 'model': 'qwen3-8b'})[0] == 200
    time.sleep(.5)
    assert balances(gateway)['vllm-rolling-day'] == 20
    print('PASS shared Valkey: migration preserves usage; both APIs deny/recover together; clouds stay independent', flush=True)

    run(ENGINE, 'exec', '--detach', gateway.name + '-mock', 'python3', '-c',
        'from provider import Provider; import threading; '
        'p=Provider(ports=(18082,18083,19002),openai_authorization="Bearer synthetic-anthropic"); '
        'p.start(); threading.Event().wait()')
    gateway.custom = {'team': {'openai_url': 'https://openai.example.test/v1',
                               'anthropic_url': 'https://messages.example.test', 'secret': 'fixture'}}
    gateway.arguments += ['-e', 'CUSTOM_TEAM_API_KEY=synthetic-anthropic']
    gateway.change(True, True)
    for path in ('/v1/responses', '/v1/chat/completions', '/v1/messages'):
        for stream in (False, True):
            status, payload, _ = gateway.request('/providers/team' + path, body=request_body(path, stream, tools=True))
            assert status == 200, (path, status, payload[:300])
            check(path, payload, stream, tool=True)
    assert gateway.request('/providers/team/v1/models', method='GET')[0] == 200
    assert balances(gateway)['vllm-rolling-day'] == 20
    gateway.quota_overrides, _ = quota_plan(gateway.config, gateway.quota_overrides, 10, provider='team')
    gateway.change(True, True)
    assert gateway.request('/providers/team/v1/responses', body=request_body('/v1/responses'))[0] == 429
    assert gateway.request('/v1/responses', body=request_body('/v1/responses'))[0] == 200
    if gateway.scenario == 'remote':
        assert gateway.request('/providers/team/v1/models', method='GET', bearer='invalid')[0] == 401
    print('PASS custom provider: Chat, Responses, Messages, streaming tools, models, secret injection and independent quotas', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("all-in-one", "remote"), default="all-in-one")
    parser.add_argument("--valkey", action="store_true")
    parser.add_argument("--extended", action="store_true")
    args = parser.parse_args()
    if args.extended and not args.valkey:
        parser.error("--extended requires --valkey")
    with ProvidersGateway(args.scenario, "valkey" if args.valkey else "memory") as gateway:
        if args.extended:
            exercise_extended(gateway)
        else:
            exercise_capacities(gateway)
            exercise(gateway)


if __name__ == "__main__":
    main()
