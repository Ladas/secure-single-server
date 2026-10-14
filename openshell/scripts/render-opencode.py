#!/usr/bin/env python3
import json, sys
src, dest, port, model, prefix = sys.argv[1:]
data = json.load(open(src))
provider = data['provider']['praxis']
provider['options']['baseURL'] = f'http://host.openshell.internal:{port}{prefix}/v1'
model_config = provider['models']['@@MODEL_ID@@']
if prefix == '/vllm':
    model_config['limit'] = {'context': 16384, 'output': 4096}
    model_config['reasoning'] = True
    model_config['interleaved'] = {'field': 'reasoning'}
    # vLLM's OpenAI-compatible server expects the classic parameter surface;
    # the native adapter and forceReasoning are for OpenAI's current models.
    model_config.pop('options', None)
    provider['npm'] = '@ai-sdk/openai-compatible'
provider['models'] = {model: model_config}
data['model'] = 'praxis/' + model
with open(dest, 'w') as out:
    json.dump(data, out)
