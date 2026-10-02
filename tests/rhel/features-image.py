#!/usr/bin/env python3
"""Exercise the RHEL quota-check logic against real Praxis with disposable containers."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import uuid

from features import checks, quota_config

spec = importlib.util.spec_from_file_location("provider_image", Path(__file__).with_name("provider-image.py"))
providers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(providers)
from gateway import Gateway, ENGINE, run
from evidence import save


class FeatureGateway(providers.ProvidersGateway):
    openai = True
    anthropic = True


class API:
    def __init__(self, gateway):
        self.gateway = gateway
        self.model = "fixture"
        self.args = SimpleNamespace(scenario="remote-gateway" if gateway.scenario == "remote" else "all-in-one")

    def control(self, mode=None, reset=False):
        return self.gateway.control(mode, reset=reset)

    def request(self, path, body=None, token=None, method="POST"):
        status, payload, _ = self.gateway.request(path, body=body, bearer=token, method=method)
        return status, payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("all-in-one", "remote"), required=True)
    parser.add_argument("--valkey", action="store_true")
    args = parser.parse_args()
    results = {}
    profile = "valkey" if args.valkey else "memory"
    with FeatureGateway(args.scenario, profile) as gateway:
        source = copy.deepcopy(gateway.config)

        def reset():
            run(ENGINE, "rm", "--force", gateway.name)
            gateway.config = quota_config(source, uuid.uuid4().hex)
            (gateway.work / "gateway.json").write_text(json.dumps(gateway.config))
            Gateway.boot(gateway)

        checks(API(gateway), reset, results)
    save(f"features-{ENGINE}-{args.scenario}-{profile}", {"status": "passed", "checks": results,
         "scope": "container API checks only; no native CLI or RHEL pass"})
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("Run without Python -O")
    main()
