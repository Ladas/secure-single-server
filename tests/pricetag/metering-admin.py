#!/usr/bin/env python3
"""Standalone provisioning contracts for the pinned partner-user schema."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/pricetag'))
import metering_admin


class ProvisioningTest(unittest.TestCase):
    def test_budget_targets_login_and_identity_is_stable(self):
        sql = metering_admin.provision_sql('alice', "Alice O'Neil", 5)
        self.assertIn("'user', 'alice', 5", sql)
        self.assertIn("Alice O''Neil", sql)
        self.assertIn('partner_user_logins', sql)
        self.assertIn('org_audit', sql)
        self.assertNotIn('person_identities', sql)
        self.assertIn('BEGIN;', sql)
        self.assertIn('COMMIT;', sql)

    def test_rotation_does_not_change_budget_or_role(self):
        sql = metering_admin.provision_sql('alice', None, None)
        self.assertNotIn('quota_overrides', sql)
        self.assertNotIn("role='super_admin'", sql)
        self.assertIn('active', sql)

    def test_only_explicit_admin_bootstrap_grants_admin(self):
        self.assertNotIn("role='super_admin'", metering_admin.provision_sql('admin', None, None))
        self.assertIn("role='super_admin'", metering_admin.provision_sql('admin', None, None, admin=True))
        with self.assertRaises(ValueError):
            metering_admin.provision_sql('alice', None, None, admin=True)

    def test_reject_invalid_identity_and_budget(self):
        for subject, amount in [("a' OR true", 5), ('alice', float('nan')), ('alice', 0), ('alice', .001)]:
            with self.assertRaises(ValueError):
                metering_admin.provision_sql(subject, None, amount)


if __name__ == '__main__':
    unittest.main()
