#!/usr/bin/env python3
"""Move the pinned local Valkey vLLM ledgers into one shared budget."""
import json

import quota_config
import quota_status

# Refuse to overwrite a ledger. Copies retain original timestamps; old ledgers
# remain available with the configuration rollback. No credential appears here.
COPY = """
if redis.call('EXISTS', KEYS[1], KEYS[2], KEYS[3]) ~= 0 then
  return redis.error_reply('shared vLLM ledger already exists; inspect the previous migration')
end
local records = cjson.decode(ARGV[2])
for i, entry in ipairs(records) do
  redis.call('ZADD', KEYS[1], entry[1], 'settled:' .. i .. ':' .. entry[2])
end
redis.call('SET', KEYS[3], #records)
redis.call('PEXPIRE', KEYS[1], ARGV[1])
return #records
"""


def records(snapshot, window, timeout):
    """Preserve settlements and conservatively retain interrupted reservations."""
    quota_status.valkey_balance(snapshot, window, timeout)  # Validate the pinned format.
    seconds, micros, settled, active = snapshot
    now = int(seconds) * 1000 + int(micros) // 1000
    result = [[int(at), int(member.rsplit(':', 1)[1])]
              for member, at in zip(settled[::2], settled[1::2]) if int(at) > now - window]
    for value in active[1::2]:
        amount, at = map(int, value.split('|'))
        if at > now - window:
            result.append([at, amount])
    return result


def prepare(installed):
    """Validate the supported layout and capture a private client before stopping Praxis."""
    entries = quota_config.entries(installed)
    names = ['vllm-openai-rolling-day', 'vllm-anthropic-rolling-day']
    found = [entries[n] for n in names if n in entries]
    if not found:
        return None
    for item, rule in found:
        api = rule['name'].split('-')[1]
        if (item.get('backend') != {'kind': 'valkey', 'url': '${TOKEN_RATE_LIMIT_VALKEY_URL}',
                                  'namespace': 'secure-single-server:limits:vllm-' + api}
                or item.get('key', 'global') != 'global' or rule.get('algorithm') != 'sliding_window'
                or rule.get('window') != '24h' or rule.get('reservation_timeout') != '300s'):
            raise ValueError('shared migration requires the managed global Valkey 24h/300s vLLM rules')
    image = json.loads(quota_status.service('podman', 'inspect', 'praxis-shared-gateway',
                                           '--format', '{{json .ImageName}}'))
    if image.rsplit('@', 1)[-1] != quota_status.LEDGER_IMAGE:
        raise ValueError('shared migration is not qualified for this Praxis image')
    query = quota_status.valkey_client()

    def copy_stopped():
        combined = []
        for item, rule in found:
            keys = quota_status.valkey_keys(item['backend']['namespace'], rule['name'])
            snapshot = json.loads(query('EVAL', quota_status.LEDGER_READ, '2', *keys, '86400000'))
            combined.extend(records(snapshot, 86400000, 300000))
        namespace = 'secure-single-server:limits:vllm'
        keys = quota_status.valkey_keys(namespace, 'vllm-rolling-day')
        # The sequence key is namespace-wide in the pinned backend.
        result = query('-x', 'EVAL', COPY, '3', *keys, namespace + ':reservation-seq',
                       '86700000', input_payload=json.dumps(combined))
        count = json.loads(result)
        if not isinstance(count, int):
            raise ValueError('shared quota migration failed; old ledgers retained')
        print(f'Preserved {sum(amount for _, amount in combined):,} charged tokens in {count} records.')
    return copy_stopped
