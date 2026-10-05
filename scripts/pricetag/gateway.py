#!/usr/bin/env python3
"""Render the HTTPS spending gateway from an existing native provider config."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from unified_config import catalog, render as unified, validate

INFERENCE = ['/v1/chat/completions', '/v1/responses', '/v1/messages']
DASHBOARD = ['/', '/login', '/logout', '/dashboard', '/admin', '/manager', '/me', '/welcome',
             '/whoami', '/api/v1/whoami', '/api/v1/pricing',
             '/api/v1/dashboard/overview', '/api/v1/dashboard/groups',
             '/api/v1/dashboard/users', '/api/v1/dashboard/models',
             '/api/v1/dashboard/timeline', '/api/v1/dashboard/recent',
             '/api/v1/me/quota', '/api/v1/me/quota/request',
             '/api/v1/admin/quota/policy', '/api/v1/admin/quota/overrides',
             '/api/v1/admin/quota/models', '/api/v1/admin/quota/denials',
             '/api/v1/admin/people', '/api/v1/admin/identities', '/api/v1/admin/models',
             '/api/v1/admin/org/roles', '/api/v1/admin/org/valid-groups',
             '/api/v1/admin/users', '/api/v1/org/scope', '/api/v1/org/tree',
             '/api/v1/org/usage', '/api/v1/org/person', '/api/v1/org/charts']
DASHBOARD_PREFIXES = ['/api/v1/admin/people/', '/api/v1/org/quota-requests']


def render(original, models, origins=None):
    origins = origins or ['https://localhost:8443']
    models = validate(models)
    public_catalog = catalog(models, 'openai')
    for entry, model in zip(public_catalog['data'], models):
        entry['praxis']['apis'] = model['apis']
    result = unified(original, models)
    result['admin'] = {'address': '127.0.0.1:9901'}
    result['insecure_options'] = {'allow_private_endpoints': True, 'allow_private_upstreams': True}
    result['listeners'] = [
        {'name': 'https', 'address': '0.0.0.0:8443', 'filter_chains': ['edge'],
         'tls': {'certificates': [{'cert_path': '/etc/praxis/tls.pem',
                                  'key_path': '/etc/praxis/tls-key.pem'}]}},
        {'name': 'native-openai', 'address': '127.0.0.1:18080', 'filter_chains': ['openai']},
        {'name': 'native-anthropic', 'address': '127.0.0.1:18081', 'filter_chains': ['anthropic']},
        {'name': 'authenticated-inference', 'address': '127.0.0.1:18082', 'filter_chains': ['authenticated']},
        {'name': 'metering-callout', 'address': '127.0.0.1:18083', 'filter_chains': ['callout']},
        {'name': 'credential-validation', 'address': '0.0.0.0:18084', 'filter_chains': ['validation']},
        {'name': 'dashboard-boundary', 'address': '127.0.0.1:18085', 'filter_chains': ['dashboard']}]
    for chain in result['filter_chains']:
        filters = [f for f in chain['filters'] if f['filter'] not in ('token_rate_limit', 'policy', 'rate_limit')]
        for i, item in enumerate(filters):
            if item['filter'] == 'token_count':
                filters.insert(i, {'filter': 'external_metering',
                    'metering_url': 'http://127.0.0.1:18083', 'allow_private_endpoint': True,
                    'fail_open': False, 'timeout_seconds': 5, 'source': 'secure-single-server',
                    # An empty fallback still calls metering, whose missing
                    # customer response fails closed. None would skip metering.
                    'default_username': '', 'feature_key': 'inference-tokens'})
                break
        chain['filters'] = filters

    post = [{'when': {'path_prefix': '/v1/', 'methods': ['POST']}}]
    allowed = [{'path': p} for p in DASHBOARD] + [{'path_prefix': p} for p in DASHBOARD_PREFIXES] + [
        {'path': '/v1/models', 'methods': ['GET']}] + [
        {'path': p, 'methods': ['POST']} for p in INFERENCE]
    def auth(mode):
        return {'filter': 'manual_jwt', 'mode': mode,
                'public_key_file': '/etc/praxis/jwt-public.pem',
                'registry_file': '/etc/praxis/users.json',
                'issuer': 'https://secure-single-server.local', 'audience': 'praxis-gateway',
                'allowed_origins': origins if mode == 'dashboard' else []}

    authenticated = [
        {'filter': 'request_id'},
        auth('inference'),
        {'filter': 'static_response', 'status': 200, 'body': json.dumps(public_catalog),
         'headers': [{'name': 'Content-Type', 'value': 'application/json'}],
         'conditions': [{'when': {'path': '/v1/models', 'methods': ['GET']}}]},
        {'filter': 'model_to_header', 'header': 'X-Tenant-Model', 'conditions': post},
        {'filter': 'json_body', 'on_invalid': 'reject', 'max_body_bytes': 10485760,
         'request_extract': [{'pointer': '/model', 'header': 'X-Tenant-Model'}], 'conditions': post},
        {'filter': 'router', 'routes': [
            {'path': p, 'cluster': 'native-anthropic' if p == '/v1/messages' else 'native-openai'}
            for p in INFERENCE]},
        {'filter': 'load_balancer', 'clusters': [
            {'name': 'native-openai', 'endpoints': ['127.0.0.1:18080']},
            {'name': 'native-anthropic', 'endpoints': ['127.0.0.1:18081']}]}]
    callout = [
        {'filter': 'router', 'routes': [
            {'path': '/api/v1/events', 'cluster': 'metering'},
            {'path_prefix': '/api/v1/customers/', 'cluster': 'metering'}]},
        {'filter': 'credential_injection', 'clusters': [{'name': 'metering',
            'header': 'Authorization', 'header_prefix': 'Bearer ', 'env_var': 'M2M_SHARED_SECRET'}]},
        {'filter': 'load_balancer', 'clusters': [
            {'name': 'metering', 'endpoints': ['pricetag-metering:8080']}]}]
    # Each authentication role has its own unconditional chain. The callback
    # listener is reachable only on the private container network.
    public = [
        {'filter': 'request_id'},
        {'filter': 'static_response', 'status': 404, 'body': 'Route not available',
         'conditions': [{'unless': match} for match in allowed]},
        # Dashboard navigation fans out to several authenticated API reads.
        {'filter': 'rate_limit', 'mode': 'global', 'rate': 30, 'burst': 120},
        {'filter': 'router', 'routes': [
            {'path': p, 'cluster': 'authenticated'} for p in [*INFERENCE, '/v1/models']] + [
            {'path': p, 'cluster': 'dashboard'} for p in DASHBOARD] + [
            {'path_prefix': p, 'cluster': 'dashboard'} for p in DASHBOARD_PREFIXES]},
        {'filter': 'load_balancer', 'clusters': [
            {'name': 'authenticated', 'endpoints': ['127.0.0.1:18082']},
            {'name': 'dashboard', 'endpoints': ['127.0.0.1:18085']}]}]
    result['filter_chains'] += [{'name': 'edge', 'filters': public},
        {'name': 'authenticated', 'filters': authenticated}, {'name': 'callout', 'filters': callout},
        {'name': 'validation', 'filters': [auth('callback')]},
        {'name': 'dashboard', 'filters': [auth('dashboard'),
            {'filter': 'router', 'routes': [{'path_prefix': '/', 'cluster': 'metering'}]},
            {'filter': 'load_balancer', 'clusters': [
                {'name': 'metering', 'endpoints': ['pricetag-metering:8080']}]}]}]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--providers', type=Path, required=True,
                        help='rendered all-in-one Praxis config in JSON, with two native chains')
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(render(json.loads(args.providers.read_text()),
                                             json.loads(args.models.read_text())), indent=2) + '\n')


if __name__ == '__main__':
    main()
