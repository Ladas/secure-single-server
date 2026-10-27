#!/usr/bin/env python3
"""Test bootstrap price recovery with session-local tables on the mock RHEL host."""
import importlib.machinery
import importlib.util
from pathlib import Path
import pwd
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/pricetag'))
import prepare


def main():
    loader = importlib.machinery.SourceFileLoader('benchmark', str(ROOT / 'scripts/pricetag/benchmark'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    benchmark = importlib.util.module_from_spec(spec)
    loader.exec_module(benchmark)
    benchmark.require_mock(Path('/etc/praxis-pricetag'))
    uid = pwd.getpwnam('praxis-svc').pw_uid
    command = ['sudo', '-u', 'praxis-svc', 'env', f'XDG_RUNTIME_DIR=/run/user/{uid}',
               'podman', 'exec', '-i', 'pricetag-db', 'psql', '-X', '-qAt',
               '-U', 'metering', '-d', 'metering', '-v', 'ON_ERROR_STOP=1']
    # Temporary tables shadow all bootstrap targets; no deployment data changes.
    setup = '''CREATE TEMP TABLE quota_policy (LIKE public.quota_policy INCLUDING ALL);
INSERT INTO quota_policy SELECT * FROM public.quota_policy;
CREATE TEMP TABLE model_pricing (LIKE public.model_pricing INCLUDING ALL);
CREATE TEMP TABLE usage_events (LIKE public.usage_events INCLUDING ALL);
'''
    models = [{'id': 'test/missing-price', 'model': 'missing-price', 'provider': 'external'}]
    sql = prepare.bootstrap(models, {}, 5)
    failed = subprocess.run(command, input=setup + sql, text=True, capture_output=True, cwd='/tmp')
    assert failed.returncode != 0 and 'Missing reviewed price' in failed.stderr, failed.stderr
    print('PASS: missing price blocks bootstrap')
    seed = '''INSERT INTO model_pricing(model,provider,input_cost_per_mtok,output_cost_per_mtok,
cache_write_cost_per_mtok,cache_read_cost_per_mtok) VALUES ('missing-price','external',1,2,0,0);
'''
    query = "SELECT input_cost_per_mtok=1 AND output_cost_per_mtok=2 FROM model_pricing WHERE model='test/missing-price';"
    recovered = subprocess.run(command, input=setup + seed + sql + query,
                               text=True, capture_output=True, cwd='/tmp')
    assert recovered.returncode == 0, recovered.stderr
    assert recovered.stdout.strip().splitlines()[-1] == 't', recovered.stdout
    print('PASS: reviewed source rates allow retry and populate alias rates')


if __name__ == '__main__':
    main()
