#!/usr/bin/env python3
"""Render optional providers without changing listener authentication or quota keys."""
import argparse
import copy
import json
import re
from urllib.parse import urlsplit
from pathlib import Path


class SingleValueAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if getattr(namespace, self.dest + "_seen", False):
            parser.error(option_string + " may be given only once")
        setattr(namespace, self.dest + "_seen", True)
        setattr(namespace, self.dest, values)


def validate_vllm_endpoint(endpoint):
    match = re.fullmatch(
        r"((?:0|[1-9]\d{0,2})(?:\.(?:0|[1-9]\d{0,2})){3}):(0|[1-9]\d{0,4})", endpoint)
    if not match:
        raise ValueError("vLLM endpoint must be RFC1918_IP:PORT")
    octets = [int(octet) for octet in match.group(1).split(".")]
    port = int(match.group(2))
    if any(octet > 255 for octet in octets) or not 1 <= port <= 65535:
        raise ValueError("vLLM endpoint must be RFC1918_IP:PORT")
    first, second = octets[:2]
    if not (first == 10 or first == 192 and second == 168 or
            first == 172 and 16 <= second <= 31):
        raise ValueError("vLLM endpoint host must be an RFC1918 IPv4 address")


def custom_name(name):
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", name) or name.split('-')[0] in ('vllm', 'openai', 'anthropic'):
        raise ValueError('custom provider name must be a lowercase slug, not a built-in provider')
    return name


def endpoint(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ('', '/', '/v1', '/v1/')
            or not re.fullmatch(r'[A-Za-z0-9.-]+', parsed.hostname)):
        raise ValueError('provider URL must be an HTTPS origin or /v1 URL, without credentials or query')
    port = 443 if parsed.port is None else parsed.port
    if not 0 < port < 65536:
        raise ValueError('invalid provider port')
    return {'endpoints': [f'{parsed.hostname}:{port}'], 'http': {'authority': parsed.netloc},
            'tls': {'sni': parsed.hostname}}


def render(original, *, vllm, openai, anthropic, shared_vllm=False, custom=None, vllm_endpoint=""):
    custom = custom or {}
    for name, settings in custom.items():
        custom_name(name)
        if not any(settings.get(api + '_url') for api in ('openai', 'anthropic')):
            raise ValueError('custom provider requires an OpenAI or Anthropic URL')
        for api in ('openai', 'anthropic'):
            if settings.get(api + '_url'):
                endpoint(settings[api + '_url'])
    if not (vllm or openai or anthropic or custom):
        raise ValueError("enable at least one provider")
    if vllm_endpoint and not vllm:
        raise ValueError("--vllm-endpoint requires the vLLM route")
    if vllm_endpoint:
        validate_vllm_endpoint(vllm_endpoint)
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
            choices = [(api, '', False, openai if api == 'openai' else anthropic, None),
                       ('vllm', '/vllm', True, vllm, None)]
            choices += [(slug + '-' + api, '/providers/' + slug, False, bool(settings.get(api + '_url')), slug)
                        for slug, settings in custom.items()]
            for name, prefix, local, enabled, slug in choices:
                if not enabled:
                    continue
                paths = ["/v1/messages", "/v1/messages/count_tokens"] if api == "anthropic" else [
                    "/v1/responses", "/v1/chat/completions", "/v1/models"]
                for path in paths:
                    routes.append({"path_prefix" if path == "/v1/responses" else "path": prefix + path, "cluster": name})
                # The Messages listener also needs model discovery. A shared
                # cloud URL retains OpenAI's catalog when both clouds are on.
                openai_catalog = bool(custom[slug].get("openai_url")) if slug else openai
                if api == "anthropic" and (not remote or (not local and not openai_catalog)):
                    routes.append({"path": prefix + "/v1/models", "cluster": name})
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
                if slug:
                    quota['rules'][0]['name'] = slug + '-' + api + '-rolling-day'
                    if quota['backend']['kind'] == 'valkey':
                        quota['backend']['namespace'] = 'secure-single-server:limits:' + slug + '-' + api
                limits.append(quota)
                counters.append({"filter": "token_count", "provider": api, "conditions": copy.deepcopy(conditions)})
                if slug:
                    upstreams.append({'name': name, **endpoint(custom[slug][api + '_url'])})
                    key = copy.deepcopy(credentials[api])
                    key.update(name=name, env_var='CUSTOM_' + slug.upper().replace('-', '_') + '_API_KEY')
                    keys.append(key)
                elif not local:
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
            upstream = {"name": "vllm", "endpoints": [vllm_endpoint or "praxis-vllm:8000"]}
            if vllm_endpoint:
                upstream["http"] = {"authority": vllm_endpoint}
            upstreams.append(upstream)
        for slug in custom:
            prefix = '/providers/' + slug
            filters.append({'filter': 'path_rewrite', 'strip_prefix': prefix, 'allow_rewrite_override': True, 'conditions': [
                {'when': {'path_prefix': prefix + '/'}}]})
        filters.append({"filter": "load_balancer", "clusters": upstreams})
        chain["filters"] = filters
    if vllm:
        config.setdefault("insecure_options", {}).update(
            allow_private_endpoints=True, allow_private_upstreams=True)
    if shared_vllm:
        for chain in config['filter_chains']:
            found = [f for f in chain['filters'] if f['filter'] == 'token_rate_limit'
                     and f['rules'][0]['name'].startswith('vllm-')]
            for quota in found:
                if quota['backend']['kind'] != 'valkey':
                    raise ValueError('a shared vLLM quota requires Valkey')
                quota['rules'][0]['name'] = 'vllm-rolling-day'
                quota['backend']['namespace'] = 'secure-single-server:limits:vllm'
                quota['conditions'] = [{'when': {'methods': ['POST']}},
                    {'when': {'path_prefix': '/vllm/v1/'}},
                    {'unless': {'path': '/vllm/v1/messages/count_tokens'}}]
            # The remote gateway has both APIs in one chain: admit only once.
            for quota in found[1:]:
                chain['filters'].remove(quota)
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument('--existing-state', type=Path)
    parser.add_argument("--vllm", action="store_true")
    parser.add_argument("--vllm-endpoint", default=None, action=SingleValueAction)
    parser.add_argument("--openai-secret", default="")
    parser.add_argument("--anthropic-secret", default="")
    args = parser.parse_args()
    if args.vllm_endpoint is not None and not args.vllm_endpoint:
        parser.error("vllm endpoint must be RFC1918_IP:PORT")
    import yaml
    path = args.directory / "shared-gateway.yaml"
    previous = json.loads(args.existing_state.read_text()) if args.existing_state and args.existing_state.exists() else {}
    config = render(yaml.safe_load(path.read_text()), vllm=args.vllm,
                    openai=bool(args.openai_secret), anthropic=bool(args.anthropic_secret), shared_vllm=previous.get("shared_vllm_quota", False),
                    custom=previous.get("custom_providers"), vllm_endpoint=args.vllm_endpoint)
    path.write_text(json.dumps(config, indent=2) + "\n")
    unit = args.directory / "praxis.container"
    lines = unit.read_text().splitlines()
    for target, secret in (("OPENAI_API_KEY", args.openai_secret), ("ANTHROPIC_API_KEY", args.anthropic_secret)):
        if not secret:
            lines = [line for line in lines if not (line.startswith("Secret=") and line.endswith("target=" + target))]
    for slug, settings in previous.get('custom_providers', {}).items():
        target = 'CUSTOM_' + slug.upper().replace('-', '_') + '_API_KEY'
        lines.insert(lines.index('[Container]') + 1, f"Secret={settings['secret']},type=env,target={target}")
    unit.write_text("\n".join(lines) + "\n")
    state = {"vllm": args.vllm, "vllm_endpoint": args.vllm_endpoint or "", "openai_secret": args.openai_secret, "anthropic_secret": args.anthropic_secret}
    if previous.get('custom_providers'):
        state['custom_providers'] = previous['custom_providers']
    if previous.get('shared_vllm_quota'):
        state['shared_vllm_quota'] = True
    (args.directory / 'providers.json').write_text(json.dumps(state, indent=2) + '\n')


if __name__ == "__main__":
    main()
