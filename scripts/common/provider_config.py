#!/usr/bin/env python3
"""Render optional providers without changing listener authentication or quota keys."""
import argparse
import copy
import json
from pathlib import Path


def render(original, *, vllm, openai, anthropic):
    if not (vllm or openai or anthropic):
        raise ValueError("enable at least one provider")
    config = copy.deepcopy(original)
    remote = len(config["listeners"]) == 1 and config["listeners"][0]["name"] == "https"
    for chain in config["filter_chains"]:
        old = chain["filters"]
        providers = ("openai", "anthropic") if remote else (chain["name"],)
        if not set(providers) <= {"openai", "anthropic"}:
            raise ValueError("optional providers support memory/valkey gateways only")
        backends = {c["name"]: c for f in old if f["filter"] == "load_balancer" for c in f["clusters"]}
        credentials = {c["name"]: c for f in old if f["filter"] == "credential_injection" for c in f["clusters"]}
        quotas = {f["rules"][0]["name"].split("-")[0]: f for f in old if f["filter"] == "token_rate_limit"}
        filters = [f for f in old if f["filter"] in ("request_id", "policy", "headers", "access_log")]
        for f in filters:
            if f["filter"] == "headers" and "X-Api-Key" not in f["request_remove"]:
                f["request_remove"].append("X-Api-Key")
        routes, limits, counters, protocols, upstreams, keys = [], [], [], [], [], []
        for api in providers:
            for local, enabled in ((False, openai if api == "openai" else anthropic), (True, vllm)):
                if not enabled:
                    continue
                name = "vllm" if local else api
                prefix = "/vllm" if local else ""
                paths = ["/v1/messages", "/v1/messages/count_tokens"] if api == "anthropic" else [
                    "/v1/responses", "/v1/chat/completions", "/v1/models"]
                for path in paths:
                    routes.append({"path_prefix" if path == "/v1/responses" else "path": prefix + path, "cluster": name})
                conditions = [{"when": {"methods": ["POST"]}}]
                if api == "anthropic":
                    conditions.append({"when": {"path": prefix + "/v1/messages"}})
                    protocols.append({"filter": "anthropic_messages_protocol", "conditions": [
                        {"when": {"path_prefix": prefix + "/v1/messages"}}]})
                else:
                    conditions += [{"when": {"path_prefix": prefix + "/v1"}},
                                   {"unless": {"path_prefix": prefix + "/v1/messages"}}]
                quota = copy.deepcopy(quotas[api])
                quota["conditions"] = conditions
                if local:
                    quota["rules"][0]["name"] = "vllm-" + quota["rules"][0]["name"]
                    if quota["backend"]["kind"] == "valkey":
                        quota["backend"]["namespace"] = "secure-single-server:limits:vllm-" + api
                limits.append(quota)
                counters.append({"filter": "token_count", "provider": api, "conditions": copy.deepcopy(conditions)})
                if not local:
                    upstreams.append(backends[api])
                    keys.append(credentials[api])
        # Disabled cloud paths have no route: fail before credentials or quota admission.
        if not routes:
            chain["filters"] = filters + [{"filter": "static_response", "status": 404, "body": "Provider disabled"}]
            continue
        filters.append({"filter": "router", "routes": routes})
        filters += [f for f in old if f["filter"] == "rate_limit"]
        filters += limits + protocols + counters
        if keys:
            filters.append({"filter": "credential_injection", "clusters": keys})
        if vllm:
            filters.append({"filter": "path_rewrite", "strip_prefix": "/vllm", "conditions": [
                {"when": {"path_prefix": "/vllm"}}]})
            upstreams.append({"name": "vllm", "endpoints": ["praxis-vllm:8000"]})
        filters.append({"filter": "load_balancer", "clusters": upstreams})
        chain["filters"] = filters
    if vllm:
        config.setdefault("insecure_options", {}).update(
            allow_private_endpoints=True, allow_private_upstreams=True)
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--vllm", action="store_true")
    parser.add_argument("--openai-secret", default="")
    parser.add_argument("--anthropic-secret", default="")
    args = parser.parse_args()
    import yaml
    path = args.directory / "shared-gateway.yaml"
    config = render(yaml.safe_load(path.read_text()), vllm=args.vllm,
                    openai=bool(args.openai_secret), anthropic=bool(args.anthropic_secret))
    path.write_text(json.dumps(config, indent=2) + "\n")
    unit = args.directory / "praxis.container"
    lines = unit.read_text().splitlines()
    for target, secret in (("OPENAI_API_KEY", args.openai_secret), ("ANTHROPIC_API_KEY", args.anthropic_secret)):
        if not secret:
            lines = [line for line in lines if not (line.startswith("Secret=") and line.endswith("target=" + target))]
    unit.write_text("\n".join(lines) + "\n")
    (args.directory / "providers.json").write_text(json.dumps({"vllm": args.vllm,
        "openai_secret": args.openai_secret, "anthropic_secret": args.anthropic_secret}, indent=2) + "\n")


if __name__ == "__main__":
    main()
