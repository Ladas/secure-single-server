"""Validated gateway-management contract shared by the host adapter and CLI.

The browser never supplies Praxis filters, file paths, commands or secret names.
Endpoint approval is deployment-owned and cannot be changed through this API.
"""
import copy
import hashlib
import json
import re
from urllib.parse import urlsplit

from unified_config import validate as validate_models


class Conflict(ValueError):
    pass


def mock_configuration():
    """Synthetic provider contract used only by the opt-in management demo."""
    return {'providers': [{'name': 'mock', 'urls': {
        'openai': 'http://pricetag-provider:18080/v1',
        'anthropic': 'http://pricetag-provider:18081'}, 'messages_auth': 'x-api-key'}],
        'models': [{'id': 'mock/' + alias, 'provider': 'mock', 'model': model,
                    'apis': ['openai', 'anthropic'], 'context': 32768, 'output': output}
                   for alias, model, output in [('fixture', 'fixture', 4096),
                                                ('demo-cheap', 'fixture-cheap', 2048)]]}


def revision(document):
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate(document, approved_origins):
    if not isinstance(document, dict) or set(document) != {'providers', 'models'}:
        raise ValueError('configuration requires providers and models')
    providers = document['providers']
    if not isinstance(providers, list) or not 1 <= len(providers) <= 20:
        raise ValueError('configure between one and twenty providers')
    names = set()
    for provider in providers:
        if not isinstance(provider, dict) or set(provider) != {'name', 'urls', 'messages_auth'}:
            raise ValueError('provider requires name, urls and messages_auth')
        name = provider['name']
        if (not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', name)
                or name in names or name in ('vllm', 'anthropic', 'pricetag')):
            raise ValueError('provider name must be unique and not reserved')
        names.add(name)
        urls = provider['urls']
        if not isinstance(urls, dict) or not urls or set(urls) - {'openai', 'anthropic'}:
            raise ValueError('provider URLs require supported API names')
        if name == 'openai' and set(urls) != {'openai'}:
            raise ValueError('the openai provider supports only its native API')
        if provider['messages_auth'] not in ('x-api-key', 'bearer'):
            raise ValueError('invalid Messages authentication scheme')
        for api, address in urls.items():
            if not isinstance(address, str):
                raise ValueError('URL must be a string')
            parsed = urlsplit(address)
            # HTTP is possible only for exact mock endpoints approved by the
            # installer. Production approval admits HTTPS origins only.
            if (parsed.scheme not in ('https', 'http') or not parsed.hostname
                    or parsed.username or parsed.password or parsed.query or parsed.fragment
                    or parsed.path != ('/v1' if api == 'openai' else '')
                    or parsed.netloc != parsed.netloc.lower()):
                raise ValueError('use a canonical provider URL without credentials')
            origin = parsed.scheme + '://' + parsed.netloc
            if origin not in approved_origins:
                raise ValueError('provider origin is not approved by the host administrator')
    models = validate_models(document['models'])
    by_name = {p['name']: p for p in providers}
    for model in models:
        provider = by_name.get(model['provider'])
        if provider is None or set(model['apis']) - set(provider['urls']):
            raise ValueError('model requires a configured provider and API')
        if model['id'] == model['model']:
            raise ValueError('use a distinct gateway alias for stable pricing')
    return copy.deepcopy({'providers': providers, 'models': models})


def check_update(current, expected_revision, proposed, approved_origins):
    if not isinstance(expected_revision, str) or expected_revision != revision(current):
        raise Conflict('configuration changed; reload before saving')
    return validate(proposed, approved_origins)


def native_inputs(document):
    """Compile narrowly typed settings to native provider inputs for gateway.py."""
    chains = []
    for api in ('openai', 'anthropic'):
        clusters, credentials = [], []
        for provider in document['providers']:
            address = provider['urls'].get(api)
            if not address:
                continue
            parsed = urlsplit(address)
            name = provider['name']
            cluster = name if name == 'openai' else name + '-' + api
            port = parsed.port or (443 if parsed.scheme == 'https' else 80)
            backend = {'name': cluster, 'endpoints': [f'{parsed.hostname}:{port}'],
                       'http': {'authority': parsed.netloc}}
            if parsed.scheme == 'https':
                backend['tls'] = {'sni': parsed.hostname}
            clusters.append(backend)
            bearer = api == 'openai' or provider['messages_auth'] == 'bearer'
            credentials.append({'name': cluster,
                'env_var': 'OPENAI_API_KEY' if name == 'openai' else 'CUSTOM_' + name.upper().replace('-', '_') + '_API_KEY',
                'header': 'Authorization' if bearer else 'x-api-key',
                'header_prefix': 'Bearer ' if bearer else ''})
        chains.append({'name': api, 'filters': [
            {'filter': 'headers', 'request_remove': ['Authorization', 'X-Api-Key']},
            {'filter': 'credential_injection', 'clusters': credentials},
            {'filter': 'load_balancer', 'clusters': clusters}]})
    return {'filter_chains': chains}


def merge_gateway(current, document):
    """Replace model-dependent chains/catalog while preserving the public boundary."""
    from gateway import render
    generated = render(native_inputs(document), document['models'])
    result = copy.deepcopy(current)
    fresh = {chain['name']: chain for chain in generated['filter_chains']}
    names = [chain['name'] for chain in result['filter_chains']]
    if names.count('openai') != 1 or names.count('anthropic') != 1 or names.count('edge') != 1:
        raise ValueError('unexpected gateway chain layout')
    for index, chain in enumerate(result['filter_chains']):
        if chain['name'] in ('openai', 'anthropic'):
            result['filter_chains'][index] = fresh[chain['name']]
        elif chain['name'] == 'edge':
            def catalogs(value):
                return [f for f in value['filters'] if f['filter'] == 'static_response' and
                        f.get('conditions') == [{'when': {'path': '/v1/models', 'methods': ['GET']}}]]
            old, new = catalogs(chain), catalogs(fresh['edge'])
            if len(old) != 1 or len(new) != 1:
                raise ValueError('unexpected catalog layout')
            old[0]['body'] = new[0]['body']
    return result


class Engine:
    """Serialize updates through a backend providing the CLI's deployment lock.

    The backend owns files, secret references, activation and rollback. Returned
    state contains only reviewed configuration, never credential values.
    """
    def __init__(self, backend, approved_origins):
        self.backend = backend
        self.approved_origins = approved_origins

    def __call__(self, method, path, payload):
        with self.backend.lock():
            current = self.backend.read()
            if method == 'GET' and path == '/config':
                return {'revision': revision(current), 'configuration': current,
                        'approved_origins': list(self.approved_origins)}
            if method == 'PUT' and path == '/config':
                if not isinstance(payload, dict) or set(payload) != {'revision', 'configuration', 'credentials'}:
                    raise ValueError('update requires revision, configuration and write-only credentials')
                document = check_update(current, payload['revision'], payload['configuration'], self.approved_origins)
                credentials = payload['credentials']
                names = {p['name'] for p in document['providers']}
                if (not isinstance(credentials, dict) or set(credentials) - names or
                        any(not isinstance(v, str) or not 1 <= len(v) <= 8192 or
                            any(ord(c) < 32 or ord(c) > 126 for c in v) for v in credentials.values())):
                    raise ValueError('invalid provider credentials')
                self.backend.activate(document, credentials)
                return {'revision': revision(document), 'configuration': document}
            if method == 'POST' and path == '/discover':
                if not isinstance(payload, dict) or set(payload) != {'provider', 'api', 'credential'}:
                    raise ValueError('discovery requires provider, api and credential')
                provider = next((p for p in current['providers'] if p['name'] == payload['provider']), None)
                if provider is None or payload['api'] not in provider['urls']:
                    raise ValueError('select a configured provider API')
                credential = payload['credential']
                if not isinstance(credential, str) or not 1 <= len(credential) <= 8192 or any(ord(c) < 32 or ord(c) > 126 for c in credential):
                    raise ValueError('credential required')
                # URLs come from validated, deployed state, not the discovery body.
                validate(current, self.approved_origins)
                return {'models': self.backend.discover(provider, payload['api'], credential)}
            raise ValueError('unsupported operation')
