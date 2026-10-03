#!/usr/bin/env python3
import importlib.machinery
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[2] / 'scripts/aws/https-access'
loader = importlib.machinery.SourceFileLoader('https_access', str(path))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


class HTTPSAccess(unittest.TestCase):
    def test_add_preserves_ssh_and_is_idempotent(self):
        state = {'Ingress': module.vm.ingress('all-in-one', '8.8.8.8/32')}
        desired, rule = module.proposal(state, '8.8.8.8/32')
        self.assertEqual(state['Ingress'], desired['Ingress'][:1])
        self.assertEqual(len(state['Ingress']), 1)
        self.assertEqual(len(desired['Ingress']), 2)
        self.assertEqual(rule['FromPort'], 8443)
        self.assertEqual(module.proposal(desired, '8.8.8.8/32')[0], desired)
        module.vm.check_ingress({'IpPermissions': desired['Ingress']}, desired)

    def test_refuses_broad_private_and_changed_access(self):
        state = {'Ingress': []}
        for cidr in ['0.0.0.0/0', '8.8.8.0/24', '127.0.0.1/32', '10.0.0.1/32', '::1/128']:
            with self.assertRaises(ValueError):
                module.proposal(state, cidr)
        desired, _ = module.proposal(state, '8.8.8.8/32')
        with self.assertRaises(ValueError):
            module.proposal(desired, '1.1.1.1/32')
        with self.assertRaises(ValueError):
            module.vm.check_ingress({'IpPermissions': desired['Ingress'] + [
                {'IpProtocol': 'tcp', 'FromPort': 5432, 'ToPort': 5432, 'IpRanges': []}]}, desired)


if __name__ == '__main__':
    unittest.main()
