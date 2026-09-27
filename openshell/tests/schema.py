#!/usr/bin/env python3
"""Parse every profile with the pinned CLI; an unreachable endpoint prevents creation."""
import os
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
cli = os.environ.get('OPENSHELL_BIN', '/usr/local/bin/openshell')
policies = sorted((root / 'openshell/harnesses').glob('*/profiles/*/policy.yaml'))
policies += sorted((root / 'configs/openshell-praxis/profiles').glob('*/policy.yaml'))
with tempfile.TemporaryDirectory() as td:
    for source in policies:
        policy = Path(td) / 'policy.yaml'
        policy.write_text(source.read_text().replace('@@PRAXIS_PORT@@', '8080'))
        result = subprocess.run([cli, 'sandbox', 'create', '--detach', '--no-auto-providers',
                                 '--gateway-endpoint', 'http://127.0.0.1:1',
                                 '--policy', str(policy)], capture_output=True, text=True, timeout=20)
        output = result.stdout + result.stderr
        assert result.returncode != 0 and 'connect' in output.lower(), (str(source), output)
        assert not any(word in output.lower() for word in ('decode', 'type mismatch', 'parse policy')), output
        print('schema: OK', source.relative_to(root))
