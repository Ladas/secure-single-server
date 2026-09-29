#!/usr/bin/env python3
"""Real pinned Praxis with local vLLM and independent cloud-provider fixtures."""
import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tests/common"), str(ROOT / "scripts/common")]
from gateway import ENGINE, Gateway, run, request_body
from contracts import check
from provider_config import render


class ProvidersGateway(Gateway):
    openai = False
    anthropic = False

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
        self.config = render(self.baseline, vllm=True, openai=self.openai, anthropic=self.anthropic)
        for chain in self.config["filter_chains"]:
            for f in chain["filters"]:
                if f["filter"] == "load_balancer":
                    for cluster in f["clusters"]:
                        if cluster["name"] == "vllm":
                            cluster["endpoints"] = ["127.0.0.1:8000"]
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
        self.boot()

    def request(self, path, **kwargs):
        # Gateway.request selects the Messages listener from the unprefixed path.
        old = self.openai_port
        if path.startswith("/vllm/v1/messages"):
            self.openai_port = self.anthropic_port
        try:
            return super().request(path, **kwargs)
        finally:
            self.openai_port = old


def exercise(gateway):
    for openai, anthropic in ((False, False), (True, False), (True, True), (False, True)):
        if (gateway.openai, gateway.anthropic) != (openai, anthropic):
            gateway.change(openai, anthropic)
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("all-in-one", "remote"), default="all-in-one")
    parser.add_argument("--valkey", action="store_true")
    args = parser.parse_args()
    with ProvidersGateway(args.scenario, "valkey" if args.valkey else "memory") as gateway:
        exercise(gateway)


if __name__ == "__main__":
    main()
