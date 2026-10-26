#!/usr/bin/env python3
"""Controlled model driving OpenCode's real write and bash tools, without keys."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
import provider

MARKER = 'OPENCODE_TOOL_OK'
original_completion = provider.completion


def continuation(path, body):
    return any(item.get('role') == 'tool' and item.get('tool_call_id') == 'call_bash'
               for item in body.get('messages', []))


def completion(path, body, missing_usage=False):
    result = original_completion(path, body, missing_usage)
    choice = result['choices'][0]
    message = choice['message']
    # Chat-completions tools arrive wrapped ({function: {name}}) or flat
    # ({name}), depending on the client SDK's serialization.
    names = {(tool.get('function') or tool).get('name') for tool in body.get('tools', [])}
    if not names or continuation(path, body):
        message.pop('tool_calls', None)
        message['content'] = MARKER
        choice['finish_reason'] = 'stop'
        return result
    # The pinned image's opencode has no separate write tool (apply_patch
    # owns file edits), so the proof is written through bash itself.
    if 'bash' not in names:
        raise RuntimeError('OpenCode did not advertise a bash tool; advertised: '
                           + ', '.join(sorted(name for name in names if name)))
    message['content'] = None
    message['tool_calls'] = [{'id': 'call_bash', 'type': 'function', 'function': {
        'name': 'bash',
        'arguments': json.dumps({
            'command': "node -e \"require('node:fs').writeFileSync('/sandbox/opencode-exec-proof.txt', 'OPENCODE_TOOL_OK');\"",
            'description': 'Write the proof file', 'timeout': 10000})}}]
    choice['finish_reason'] = 'tool_calls'
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=18000)
    parser.add_argument('--control-port', type=int, default=0,
                        help='also serve the /state records endpoint on this port')
    parser.add_argument('--model', default='fixture-model',
                        help='model id the fixture lists and, in local mode, the only one it serves')
    parser.add_argument('--authorization-env',
                        help='environment variable holding the bearer token; switches to non-local '
                             'mode where any model is served and this Authorization header is required')
    args = parser.parse_args()
    provider.continuation = continuation
    provider.completion = completion
    local = args.authorization_env is None
    authorization = ('Bearer ' + os.environ[args.authorization_env]) if args.authorization_env \
        else 'Bearer synthetic-openai'
    fixture = provider.Provider(host='127.0.0.1', control_host='127.0.0.1',
                                ports=(args.port, 0, args.control_port), model=args.model,
                                local=local, openai_authorization=authorization)
    fixture.start()
    print('fixture ready', flush=True)
    threading.Event().wait()


if __name__ == '__main__':
    main()
