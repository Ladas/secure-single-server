"""Explicit model routes on the two native all-in-one API listeners."""
import copy
import json
import re

MODEL_HEADER = 'X-Gateway-Model'
PROVIDER_HEADER = 'X-Gateway-Provider'


def validate(models):
    if not isinstance(models, list) or not models or len(models) > 100:
        raise ValueError('models must be a nonempty list of at most 100 entries')
    seen = set()
    required = {'id', 'provider', 'model', 'apis', 'context', 'output'}
    for item in models:
        if not isinstance(item, dict) or set(item) != required:
            raise ValueError('each model requires exactly id, provider, model, apis, context and output')
        for field in ('id', 'model'):
            if not isinstance(item[field], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}', item[field]):
                raise ValueError('invalid model ' + field)
        if not isinstance(item['provider'], str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,31}', item['provider']):
            raise ValueError('invalid model provider')
        if item['id'] in seen:
            raise ValueError('duplicate model id: ' + item['id'])
        seen.add(item['id'])
        if (not isinstance(item['apis'], list) or not item['apis']
                or any(api not in ('openai', 'anthropic') for api in item['apis'])
                or len(set(item['apis'])) != len(item['apis'])):
            raise ValueError('apis must contain openai and/or anthropic without duplicates')
        if item['provider'] in ('openai', 'anthropic') and item['apis'] != [item['provider']]:
            raise ValueError('built-in cloud providers require their native API')
        if (type(item['context']) is not int or type(item['output']) is not int
                or not 0 < item['output'] < item['context'] <= 2000000):
            raise ValueError('model limits require 0 < output < context <= 2000000')
    return copy.deepcopy(models)


def cluster_name(item, api):
    provider = item['provider']
    return provider if provider in ('vllm', 'openai', 'anthropic') else provider + '-' + api


def active(models, config, api):
    names = {c['name'] for chain in config['filter_chains'] for f in chain['filters']
             if f['filter'] == 'load_balancer' for c in f['clusters']}
    return [m for m in models if api in m['apis'] and cluster_name(m, api) in names]


def catalog(models, api):
    def limits(m):
        return {'provider': m['provider'], 'upstream_model': m['model'],
                'context': m['context'], 'output': m['output']}
    if api == 'openai':
        return {'object': 'list', 'data': [dict(id=m['id'], object='model', created=0,
                owned_by=m['provider'], praxis=limits(m)) for m in models]}
    return {'data': [dict(type='model', id=m['id'], display_name=m['id'],
            created_at='1970-01-01T00:00:00Z', praxis=limits(m)) for m in models], 'has_more': False,
            'first_id': models[0]['id'] if models else None, 'last_id': models[-1]['id'] if models else None}


def render(original, models, *, hide_vllm_reasoning=False):
    models = validate(models)
    if {c['name'] for c in original['filter_chains']} != {'openai', 'anthropic'}:
        raise ValueError('unified listeners currently require the all-in-one scenario')
    result = copy.deepcopy(original)
    for chain in result['filter_chains']:
        api, old = chain['name'], chain['filters']
        selected = active(models, original, api)
        filters = [f for f in old if f['filter'] in ('request_id', 'access_log', 'headers', 'policy', 'rate_limit')]
        sanitizer = next(f for f in filters if f['filter'] == 'headers')
        sanitizer['request_remove'] += [MODEL_HEADER, PROVIDER_HEADER]
        filters += [{'filter': 'static_response', 'status': 200,
                     'body': json.dumps(catalog(selected, api)),
                     'headers': [{'name': 'Content-Type', 'value': 'application/json'}],
                     'conditions': [{'when': {'methods': ['GET'], 'path': '/v1/models'}}]}]
        if not selected:
            chain['filters'] = filters + [{'filter': 'static_response', 'status': 404, 'body': 'No enabled models'}]
            continue
        filters += [{'filter': 'static_response', 'status': 405, 'body': 'Unsupported method',
                     'conditions': [{'unless': {'methods': ['POST']}}]},
                    # This classifier strips caller copies during body pre-read.
                    # A request-phase headers filter alone runs too late for this.
                    {'filter': 'model_to_header', 'header': MODEL_HEADER,
                     'conditions': [{'when': {'methods': ['POST']}}]},
                    {'filter': 'json_body', 'on_invalid': 'reject', 'max_body_bytes': 10485760,
                     'conditions': [{'when': {'methods': ['POST']}}],
                     'request_extract': [{'pointer': '/model', 'header': MODEL_HEADER}]}]
        paths = ['/v1/responses', '/v1/chat/completions'] if api == 'openai' else [
            '/v1/messages', '/v1/messages/count_tokens']
        filters.append({'filter': 'static_response', 'status': 404, 'body': 'Unknown model',
                        'conditions': [{'unless': {'headers': {MODEL_HEADER: m['id']}}} for m in selected]})
        filters.append({'filter': 'static_response', 'status': 404, 'body': 'Unsupported API path',
                        'conditions': [{'unless': {'path': path}} for path in paths]})
        filters.append({'filter': 'router', 'routes': [
            {'path': path, 'headers': {MODEL_HEADER: m['id']}, 'cluster': cluster_name(m, api)}
            for m in selected for path in paths]})
        for item in selected:
            conditions = [{'when': {'methods': ['POST'], 'headers': {MODEL_HEADER: item['id']}}}]
            filters += [{'filter': 'json_body', 'on_invalid': 'reject',
                         'request_replace': [{'pointer': '/model', 'value': item['model']}],
                         'conditions': conditions}]
            if hide_vllm_reasoning and api == 'openai' and item['provider'] == 'vllm':
                # Keep model thinking enabled; prevent plaintext reasoning output
                # from entering histories later replayed to a hosted Responses API.
                filters.append({'filter': 'json_body', 'on_invalid': 'reject',
                    'request_add': [{'pointer': '/include_reasoning', 'value': False}],
                    'conditions': [{'when': {'methods': ['POST'], 'path': '/v1/responses',
                                             'headers': {MODEL_HEADER: item['id']}}}]})
        for quota in (f for f in old if f['filter'] == 'token_rate_limit'):
            rule = quota['rules'][0]['name']
            provider = 'vllm' if rule.startswith('vllm-') else rule.removesuffix('-rolling-day')
            quota['conditions'] = [{'when': {'bound_upstream': {'application_provider': provider}}},
                                   {'unless': {'path': '/v1/messages/count_tokens'}}]
            filters.append(quota)
        if api == 'anthropic':
            filters.append({'filter': 'anthropic_messages_protocol'})
        filters.append({'filter': 'token_count', 'provider': api,
                        'conditions': [{'unless': {'path': '/v1/messages/count_tokens'}}]})
        filters += [f for f in old if f['filter'] in ('credential_injection', 'load_balancer')]
        for item in filters:
            if item['filter'] == 'load_balancer':
                for cluster in item['clusters']:
                    cluster.setdefault('http', {})['application_provider'] = cluster['name']
        chain['filters'] = filters
    return result
