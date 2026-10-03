#!/usr/bin/env python3
"""HTTPS/JWT, accounting and USD-denial acceptance against scripts/pricetag/local."""
import http.client
import json
from pathlib import Path
import ssl
import subprocess
import sys
import time
import urllib.parse
import uuid

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / '.state/pricetag'
CONTEXT = ssl.create_default_context(cafile=str(STATE / 'tls/ca.pem'))


def request(path, user=None, *, method='GET', body=None, headers=None):
    outgoing = dict(headers or {})
    if user:
        if path.startswith('/v1/'):
            outgoing['Authorization'] = 'Bearer ' + (STATE / (user + '.jwt')).read_text().strip()
        else:
            outgoing['Cookie'] = login(user)
            outgoing.setdefault('Origin', 'https://localhost:8443')
    if isinstance(body, dict):
        body = json.dumps(body)
        outgoing['Content-Type'] = 'application/json'
    connection = http.client.HTTPSConnection('localhost', 8443, context=CONTEXT, timeout=20)
    connection.request(method, path, body=body, headers=outgoing)
    response = connection.getresponse()
    result = response.status, response.read(), {k.lower(): v for k, v in response.getheaders()}
    connection.close()
    return result


def await_credential(user, status=200):
    # macOS Podman shares the host filesystem through a VM. Atomic rename can
    # briefly yield ENOENT there; authentication must fail closed until visible.
    for _ in range(50):
        result = request('/v1/models', user)
        if result[0] == status:
            return
        time.sleep(.1)
    expect(status, result)


def expect(status, result):
    assert result[0] == status, f'expected HTTP {status}, got {result[0]}: {result[1][:180]!r}'
    return result


def data(result):
    return json.loads(result[1])


def admin(path, body, method='POST'):
    return request(path, 'admin', method=method, body=body)


def login(user):
    token = (STATE / (user + '.jwt')).read_text().strip()
    result = expect(302, request('/login', method='POST',
        body=urllib.parse.urlencode({'api_key': token}),
        headers={'Content-Type': 'application/x-www-form-urlencoded', 'Origin': 'https://localhost:8443'}))
    cookie = result[2]['set-cookie']
    assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=Lax' in cookie
    return cookie.split(';')[0]


def sql(query):
    result = subprocess.run(['podman', 'exec', '-i', 'praxis-pricetag-db', 'psql', '-U', 'metering',
        '-d', 'metering', '-v', 'ON_ERROR_STOP=1', '-At'], input=query, text=True,
        capture_output=True, check=True)
    return result.stdout.strip()


def main():
    for _ in range(60):
        try:
            expect(200, request('/login'))
            break
        except (OSError, AssertionError):
            time.sleep(.5)
    else:
        raise AssertionError('gateway did not become ready')
    assert b'api_key' in expect(200, request('/login'))[1]
    expect(401, request('/v1/models'))
    expect(401, request('/v1/models', headers={'Authorization': 'Bearer invalid'}))
    assert data(expect(200, request('/v1/models', 'alice')))['data'][0]['id'] == 'demo-model'
    for path in ['/api/v1/events', '/api/v1/customers/alice/entitlements/inference-tokens/value',
                 '/ready', '/health', '/validate', '/api/v1/admin/keys', '/v1/batches']:
        expect(404, request(path, 'admin'))
    cookie = login('alice')
    expect(200, request('/dashboard', headers={'Cookie': cookie}))
    assert expect(302, request('/admin', 'alice'))[2]['location'] == '/me'
    expect(200, request('/admin', 'admin'))
    expect(403, request('/api/v1/admin/quota/policy', method='PATCH', body={'enforced': False},
                       headers={'Cookie': login('admin'), 'Origin': 'https://attacker.invalid'}))
    expect(403, request('/api/v1/admin/quota/policy', 'alice', method='PATCH', body={'enforced': False},
        headers={'X-Forwarded-User': 'admin', 'X-Forwarded-Groups': '["system:masters"]'}))
    print('PASS: TLS, JWT login, session, admin authorization and private API isolation')

    user = 'test' + uuid.uuid4().hex[:12]
    second = user + 'b'
    for subject in (user, second):
        subprocess.run([str(ROOT / 'scripts/pricetag/credentials'), 'issue', '--registry',
            str(STATE / 'gateway/users.json'), '--key',
            str(STATE / 'issuer/private.pem'), '--subject', subject, '--output', str(STATE / (subject + '.jwt'))],
            check=True, capture_output=True)
        await_credential(subject)
    result = admin('/api/v1/admin/people', {'slug': user, 'full_name': 'Budget acceptance test'})
    assert result[0] in (200, 201), (result[0], result[1][:180])
    expect(200, admin('/api/v1/admin/identities', {'username': user, 'person_slug': user}))
    expect(200, admin('/api/v1/admin/quota/overrides',
                      {'scope': 'user', 'principal': user, 'monthly_usd': 1}, 'PUT'))
    for path, extra in [('/v1/chat/completions', {}), ('/v1/responses', {'input': 'hello'}),
                        ('/v1/messages', {'max_tokens': 32})]:
        for stream in (False, True):
            body = {'model': 'demo-model', 'messages': [{'role': 'user', 'content': 'hello'}],
                    'stream': stream, **extra}
            result = expect(200, request(path, user, method='POST', body=body,
                headers={'X-Tenant-Username': 'admin', 'X-Tenant-Model': 'free-model',
                         'X-Tenant-Group': 'forged', 'X-Forwarded-User': 'admin'}))
            assert result[1], path
    for _ in range(50):
        count = int(sql(f"SELECT count(*) FROM usage_events WHERE username='{user}';"))
        if count == 6:
            break
        time.sleep(.2)
    assert count == 6, f'expected six accounted requests, got {count}'
    totals = sql(f"SELECT model,sum(prompt_tokens),sum(completion_tokens),sum(total_tokens) "
                 f"FROM usage_events WHERE username='{user}' GROUP BY model;")
    assert totals == 'demo-model|12|18|30', totals
    quota = data(expect(200, request('/api/v1/me/quota', user)))
    assert quota['enforced'] and not quota['exempt'] and quota['limit_usd'] == 1, quota
    assert abs(quota['spent_usd'] - .30) < .000001, quota
    recent = data(expect(200, request('/api/v1/dashboard/recent', user)))
    assert recent and all(row['username'] == user for row in recent), recent
    expect(403, request('/api/v1/dashboard/recent?user=' + user, second))
    print('PASS: six JSON/SSE requests across Chat, Responses and Messages charged to verified subject/model')
    expect(200, admin('/api/v1/admin/quota/overrides',
                      {'scope': 'user', 'principal': user, 'monthly_usd': .01}, 'PUT'))
    body = {'model': 'demo-model', 'messages': [{'role': 'user', 'content': 'blocked'}]}
    expect(429, request('/v1/chat/completions', user, method='POST', body=body))
    subprocess.run([str(ROOT / 'scripts/pricetag/user'), '--subject', user, '--rotate',
        '--registry', str(STATE / 'gateway/users.json'),
        '--gateway', 'https://localhost:8443', '--ca', str(STATE / 'tls/ca.pem'),
        '--key', str(STATE / 'issuer/private.pem'), '--admin-token', str(STATE / 'admin.jwt'),
        '--output', str(STATE / (user + '-renewed.jwt'))], check=True, capture_output=True)
    await_credential(user + '-renewed')
    expect(401, request('/v1/models', user))
    expect(429, request('/v1/chat/completions', user + '-renewed', method='POST', body=body))
    expect(200, request('/v1/chat/completions', second, method='POST', body=body))
    expect(200, admin('/api/v1/admin/quota/overrides',
                      {'scope': 'user', 'principal': user, 'monthly_usd': 2}, 'PUT'))
    expect(200, request('/v1/chat/completions', user + '-renewed', method='POST', body=body))
    quota = data(expect(200, request('/api/v1/me/quota', user + '-renewed')))
    assert quota['limit_usd'] == 2 and quota['spent_usd'] >= .30, quota
    print('PASS: USD denial survives rotation, old token rejected, independent user and live allowance increase')
    old_cookie = login(user + '-renewed')
    subprocess.run([str(ROOT / 'scripts/pricetag/credentials'), 'revoke', '--subject', user,
        '--registry', str(STATE / 'gateway/users.json')], check=True, capture_output=True)
    await_credential(user + '-renewed', 401)
    denied = request('/login', method='POST',
        body=urllib.parse.urlencode({'api_key': (STATE / (user + '-renewed.jwt')).read_text().strip()}),
        headers={'Content-Type': 'application/x-www-form-urlencoded', 'Origin': 'https://localhost:8443'})
    assert denied[0] == 302 and 'error=invalid' in denied[2]['location'], denied
    expect(200, request('/dashboard', headers={'Cookie': old_cookie}))
    print('PASS: revocation blocks inference and new login; existing cookie retains documented lifetime')
    assert int(sql('SELECT count(*) FROM usage_events WHERE username=\'admin\';')) == 0
    print('PASS: forged admin identity never reached the ledger')
    recovery_cookie = login(second)
    try:
        subprocess.run(['podman', 'stop', 'praxis-pricetag-metering'], check=True, capture_output=True)
        expect(503, request('/v1/chat/completions', second, method='POST', body=body))
    finally:
        subprocess.run(['podman', 'start', 'praxis-pricetag-metering'], check=True, capture_output=True)
    for _ in range(60):
        try:
            if request('/api/v1/me/quota', headers={'Cookie': recovery_cookie})[0] == 200:
                break
        except OSError:
            pass
        time.sleep(.5)
    else:
        raise AssertionError('metering did not recover after outage test')
    print('PASS: metering outage fails closed with 503; service recovered')


if __name__ == '__main__':
    main()
