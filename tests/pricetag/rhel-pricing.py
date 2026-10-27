#!/usr/bin/env python3
"""Check pricing administration through HTTPS on the mock-only RHEL gateway."""
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
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[2]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('run with sudo on the mock RHEL host')
    loader = importlib.machinery.SourceFileLoader('benchmark', str(ROOT / 'scripts/pricetag/benchmark'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    benchmark = importlib.util.module_from_spec(spec)
    loader.exec_module(benchmark)
    benchmark.require_mock(Path('/etc/praxis-pricetag'))
    os.umask(0o077)
    args.output.mkdir(mode=0o700)
    base = 'https://localhost:8443'
    tls = ssl.create_default_context(cafile='/etc/praxis-pricetag/ca.pem')
    checks = []

    def check(name, condition):
        checks.append({'check': name, 'passed': bool(condition)})
        (args.output / 'checks.json').write_text(json.dumps(checks, indent=2) + '\n')
        if not condition:
            raise RuntimeError(name)
        print('PASS: ' + name, flush=True)

    def client(key=None):
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                    urllib.request.HTTPSHandler(context=tls), urllib.request.HTTPCookieProcessor(jar))
        if key:
            req = urllib.request.Request(base + '/login', urllib.parse.urlencode({'api_key': key}).encode(),
                       headers={'Origin': base, 'Content-Type': 'application/x-www-form-urlencoded'})
            try:
                opener.open(req, timeout=15)
            except urllib.error.HTTPError as error:
                check('login succeeds', error.code == 302 and any(c.name == 'metering_session' for c in jar))
        return opener

    def request(opener, path, method='GET', data=None, headers=None):
        req = urllib.request.Request(base + path, None if data is None else json.dumps(data).encode(),
                method=method, headers={'Origin': base, 'Content-Type': 'application/json', **(headers or {})})
        try:
            with opener.open(req, timeout=120) as response:
                return response.status, json.load(response), None
        except urllib.error.HTTPError as error:
            return error.code, {'error': error.read(2048).decode(errors='replace')}, error.headers.get('Location')

    keyfile = args.output / 'user.key'
    subprocess.run([sys.executable, str(ROOT / 'scripts/pricetag/user'), '--subject',
                    'perf-pricing-' + uuid.uuid4().hex[:10], '--output', str(keyfile)],
                   check=True, stdout=subprocess.DEVNULL, cwd='/tmp')
    user = client(keyfile.read_text().strip())
    admin = client(Path('/root/pricetag-admin/admin.key').read_text().strip())
    anonymous = client()
    routes = [('/api/v1/admin/pricing-discounts', 'GET'),
              ('/api/v1/admin/pricing-discounts', 'PUT'),
              ('/api/v1/admin/pricing/refresh', 'POST'),
              ('/api/v1/admin/pricing/reprice', 'POST'),
              ('/api/v1/admin/pricing/reprice/not-an-operation', 'GET')]
    for path, method in routes:
        data = {} if method != 'GET' else None
        check('ordinary user denied: ' + method + ' ' + path,
              request(user, path, method, data)[0] == 403)
        status, _, location = request(anonymous, path, method, data,
                                     {'X-MaaS-Username': 'admin', 'X-Tenant-Username': 'admin'})
        check('anonymous/spoofed identity denied: ' + method + ' ' + path,
              status in (401, 403) or (status == 302 and location == '/login'))

    status, policy, _ = request(admin, '/api/v1/admin/pricing-discounts')
    check('admin reads discount policy', status == 200 and bool(policy.get('version')))
    check('invalid policy rejected', request(admin, '/api/v1/admin/pricing-discounts', 'PUT',
          {'version': 'invalid-test', 'rules': [{'name': 'invalid', 'provider': 'openai', 'multiplier': -1}]})[0] == 400)
    status, saved, _ = request(admin, '/api/v1/admin/pricing-discounts', 'PUT', policy)
    if status == 400 and 'pricing_discount_policy_rules_check' in saved.get('error', ''):
        print('KNOWN UPSTREAM BUG: discount save rejects object payload against array-only DB constraint', flush=True)
        checks.append({'check': 'discount policy save', 'passed': False, 'known_bug': True,
                       'reason': 'pricing_discount_policy_rules_check'})
    else:
        check('admin saves unchanged policy', status == 200)
    status, refreshed, _ = request(admin, '/api/v1/admin/pricing/refresh', 'POST', {})
    check('admin refreshes source catalog', status == 200 and not refreshed.get('error'))
    check('discount policy preserved', request(admin, '/api/v1/admin/pricing-discounts')[1] == policy)
    until = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    scope = {'model': 'fixture', 'from': (until - timedelta(hours=1)).isoformat(),
             'until': until.isoformat(), 'policy_version': policy['version'], 'confirm': False}
    status, preview, _ = request(admin, '/api/v1/admin/pricing/reprice', 'POST', scope)
    check('historical repricing dry-run available', status == 200 and preview['status'] == 'dry_run' and not preview['applied'])
    check('repricing status available', request(admin, '/api/v1/admin/pricing/reprice/' + preview['operation_id'])[0] == 200)
    check('confirmation requires bound operation and hash', request(admin, '/api/v1/admin/pricing/reprice',
          'POST', dict(scope, confirm=True))[0] == 400)
    check('dry-run remains unapplied', request(admin, '/api/v1/admin/pricing/reprice/' + preview['operation_id'])[1]['status'] == 'dry_run')
    print('No historical repricing applied. Evidence: ' + str(args.output / 'checks.json'))


if __name__ == '__main__':
    main()
