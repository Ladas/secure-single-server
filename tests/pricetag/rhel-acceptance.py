#!/usr/bin/env python3
"""Exercise SSH key/budget scripts and dashboard APIs on a mock-only RHEL host."""
import argparse
import http.cookiejar
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True, help='new private directory for test keys and sanitized evidence')
    args = p.parse_args()
    if os.geteuid() != 0:
        p.error('run with sudo on the mock RHEL host')
    loader = importlib.machinery.SourceFileLoader('benchmark', str(ROOT / 'scripts/pricetag/benchmark'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    module.require_mock(Path('/etc/praxis-pricetag'))
    os.umask(0o077)
    args.output.mkdir(mode=0o700)
    checks = []
    url = 'https://localhost:8443'
    tls = ssl.create_default_context(cafile='/etc/praxis-pricetag/ca.pem')
    noauth = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                         urllib.request.HTTPSHandler(context=tls))

    def check(name, condition):
        checks.append({'check': name, 'passed': bool(condition)})
        (args.output / 'checks.json').write_text(json.dumps(checks, indent=2) + '\n')
        if not condition:
            raise RuntimeError(name)
        print('PASS: ' + name, flush=True)

    def request(opener, path, data=None, method=None, headers=None):
        payload = None if data is None else json.dumps(data).encode()
        req = urllib.request.Request(url + path, payload, method=method,
            headers={'Content-Type': 'application/json', 'Origin': url, **(headers or {})})
        try:
            with opener.open(req, timeout=30) as response:
                raw = response.read()
                return response.status, json.loads(raw) if 'application/json' in response.headers.get('Content-Type', '') else raw.decode()
        except urllib.error.HTTPError as error:
            return error.code, None

    def login(key):
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                    urllib.request.HTTPCookieProcessor(jar), urllib.request.HTTPSHandler(context=tls))
        req = urllib.request.Request(url + '/login', urllib.parse.urlencode({'api_key': key}).encode(),
              headers={'Origin': url, 'Content-Type': 'application/x-www-form-urlencoded'})
        try:
            opener.open(req, timeout=15)
        except urllib.error.HTTPError as error:
            check('login creates a session', error.code == 302 and any(c.name == 'metering_session' for c in jar))
        return opener

    def user(*options):
        subprocess.run([sys.executable, str(ROOT / 'scripts/pricetag/user'), *options],
                       check=True, stdout=subprocess.DEVNULL, cwd='/tmp')

    subject = 'perf-accept-' + uuid.uuid4().hex[:10]
    keyfile = args.output / 'first.key'
    user('--subject', subject, '--name', 'Acceptance user', '--monthly-usd', '5', '--output', str(keyfile))
    key = keyfile.read_text().strip()
    browser = login(key)
    admin = login(Path('/root/pricetag-admin/admin.key').read_text().strip())
    check('admin page loads', request(admin, '/admin')[0] == 200)
    check('standalone UI group picker is empty',
          request(admin, '/api/v1/admin/org/valid-groups')[1] == {'groups': []})
    check('personal dashboard loads', request(browser, '/dashboard')[0] == 200)
    check('ordinary user cannot open admin page', request(browser, '/admin')[0] in (302, 403))
    check('ordinary user cannot list admin people', request(browser, '/api/v1/admin/people')[0] in (302, 403))
    check('ordinary user cannot edit quota policy', request(browser, '/api/v1/admin/quota/policy',
                                                          {'default_monthly_usd': 10000}, 'PATCH')[0] == 403)
    for path in ('/me/keys', '/api/v1/admin/keys', '/routing'):
        check('unconfigured UI route denied: ' + path, request(admin, path)[0] == 404)
    status, identities = request(admin, '/api/v1/admin/identities')
    matches = [row for row in identities if row['username'] == subject]
    check('SSH user is linked in PriceTag identities', status == 200 and len(matches) == 1)
    slug = matches[0]['person_slug']
    check('admin can read the person', request(admin, '/api/v1/admin/people/' + slug)[0] == 200)
    check('admin can edit person display name', request(admin, '/api/v1/admin/people/' + slug,
                                                      {'fields': {'full_name': 'Acceptance renamed'}}, 'PATCH')[0] == 200)
    check('personal allowance is five dollars', request(browser, '/api/v1/me/quota')[1]['limit_usd'] == 5)

    def maas(path, body=None, who=subject, method=None):
        req = urllib.request.Request('http://127.0.0.1:18086' + path,
             None if body is None else json.dumps(body).encode(), method=method,
             headers={'Content-Type': 'application/json', 'X-MaaS-Username': who,
                      'X-MaaS-Group': '["system:authenticated"]'})
        try:
            with noauth.open(req, timeout=15) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, None

    def keys():
        return maas('/v1/api-keys/search', {'filters': {'status': ['active']}})[1]['data']

    before = keys()
    user('--subject', subject, '--monthly-usd', '7', '--no-key')
    check('budget-only update does not issue a key', keys() == before)
    check('budget-only update reaches personal view', request(browser, '/api/v1/me/quota')[1]['limit_usd'] == 7)
    check('UI budget API updates allowance', request(admin, '/api/v1/admin/quota/overrides',
          {'scope': 'user', 'principal': slug, 'monthly_usd': 8}, 'PUT')[0] == 200)
    check('personal view reflects UI budget edit', request(browser, '/api/v1/me/quota')[1]['limit_usd'] == 8)
    check('another subject cannot inspect the key', maas('/v1/api-keys/' + before[0]['id'],
                                                        who=subject + '-other')[0] in (403, 404))
    check('lifetime above 90 days rejected', maas('/v1/api-keys', {'name': 'too-long', 'expiresIn': '91d'})[0] == 400)
    body = {'model': 'fixture', 'messages': [{'role': 'user', 'content': 'synthetic acceptance'}], 'max_tokens': 16}
    check('anonymous inference rejected', request(noauth, '/v1/chat/completions', body)[0] == 401)
    check('key inference succeeds', request(noauth, '/v1/chat/completions', body,
                                          headers={'Authorization': 'Bearer ' + key})[0] == 200)
    for _ in range(30):
        spending = request(browser, '/api/v1/me/quota')[1]['spent_usd']
        if spending > 0:
            break
        time.sleep(1)
    check('personal spend recorded', spending > 0)
    user('--subject', subject, '--rotate', '--key-lifetime', '30d', '--output', str(args.output / 'next.key'))
    check('rotation rejects old key', request(noauth, '/v1/chat/completions', body,
                                             headers={'Authorization': 'Bearer ' + key})[0] == 401)
    next_browser = login((args.output / 'next.key').read_text().strip())
    quota = request(next_browser, '/api/v1/me/quota')[1]
    check('rotation preserves subject, spend and allowance', quota['username'] == subject
          and quota['spent_usd'] == spending and quota['limit_usd'] == 8)
    active = keys()
    check('rotation leaves one active key', len(active) == 1)
    subprocess.run([sys.executable, str(ROOT / 'scripts/pricetag/maas-key'), 'revoke',
                    '--subject', subject, '--key-id', active[0]['id']], check=True, stdout=subprocess.DEVNULL)
    check('revoked replacement rejected', request(noauth, '/v1/chat/completions', body,
          headers={'Authorization': 'Bearer ' + (args.output / 'next.key').read_text().strip()})[0] == 401)
    check('known gap: existing browser session survives key revocation',
          request(next_browser, '/api/v1/me/quota')[0] == 200)
    print('Evidence: ' + str(args.output / 'checks.json'))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        raise SystemExit('Acceptance stopped: ' + type(error).__name__ + '; inspect sanitized checks.json') from None
