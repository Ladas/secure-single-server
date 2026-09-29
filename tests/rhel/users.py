#!/usr/bin/env python3
"""Account provisioning boundaries, without modifying local OS accounts."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("harness_user", ROOT / "scripts/common/harness_user.py")
users = importlib.util.module_from_spec(spec)
spec.loader.exec_module(users)


class UserTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.key = self.root / "login"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(self.key)], check=True)
        self.public = self.key.with_suffix(".pub")

    def test_only_one_plain_valid_public_key_is_accepted(self):
        expected = self.public.read_text().strip()
        self.assertEqual(users.public_key(self.public), expected + "\n")
        for value in (self.key.read_text(), expected + "\n" + expected,
                      'command="id" ' + expected, "ssh-ed25519 AAAA invalid", ""):
            with self.subTest(value=value[:30]):
                invalid = self.root / "invalid.pub"
                invalid.write_text(value)
                with self.assertRaises(ValueError):
                    users.public_key(invalid)

    def test_existing_account_or_home_is_never_adopted(self):
        with patch.object(users.pwd, "getpwnam", return_value=SimpleNamespace()), \
             patch.object(users, "run") as execute:
            with self.assertRaisesRegex(ValueError, "already exists"):
                users.create("tester", self.public)
            execute.assert_not_called()
        home = self.root / "tester"
        home.symlink_to(self.root / "missing")
        with patch.object(users, "HOME_ROOT", self.root), \
             patch.object(users.pwd, "getpwnam", side_effect=KeyError), \
             patch.object(users, "run") as execute:
            with self.assertRaisesRegex(ValueError, "home already exists"):
                users.create("tester", self.public)
            execute.assert_not_called()

    def test_invalid_names_never_reach_os_commands(self):
        with patch.object(users, "run") as execute:
            for name in ("root", "praxis-svc", "praxis-smoke", "openshell-svc", "--root", "../test", "has space"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    users.create(name, self.public)
            execute.assert_not_called()

    def test_create_has_private_home_key_and_no_admin_groups(self):
        bundle = self.root / "deployment"
        (bundle / "scripts/common").mkdir(parents=True)
        (bundle / "configs/common").mkdir(parents=True)
        (bundle / "scripts/common/harness.py").write_bytes((ROOT / "scripts/common/harness.py").read_bytes())
        versions = '{"opencode-ai": "1.18.32"}\n'
        (bundle / "configs/common/harness-versions.json").write_text(versions)
        home = self.root / "tester"
        account = SimpleNamespace(pw_uid=1002, pw_gid=1002, pw_dir=str(home))
        calls = []
        def execute(*command):
            calls.append(command)
            if command[0] == "useradd":
                home.mkdir()
        with patch.object(users, "ROOT", bundle), patch.object(users, "HOME_ROOT", self.root), \
             patch.object(users, "BIN_DIR", self.root / "bin"), \
             patch.object(users, "DATA_DIR", self.root / "share"), \
             patch.object(users.pwd, "getpwnam", side_effect=[KeyError, account]), \
             patch.object(users.os, "getgrouplist", return_value=[1002]), \
             patch.object(users.os, "chown") as chown, patch.object(users, "run", side_effect=execute):
            users.create("tester", self.public)
        self.assertEqual(home.stat().st_mode & 0o777, 0o700)
        self.assertEqual((home / ".ssh").stat().st_mode & 0o777, 0o700)
        authorized = home / ".ssh/authorized_keys"
        self.assertEqual(authorized.stat().st_mode & 0o777, 0o600)
        self.assertEqual(authorized.read_text(), self.public.read_text())
        self.assertTrue(any(call.args == (authorized, 1002, 1002) for call in chown.call_args_list))
        self.assertIn("--user-group", calls[0])
        self.assertNotIn("--groups", calls[0])
        self.assertIn(("restorecon", "-RF", str(home)), calls)
        self.assertTrue((self.root / "bin/praxis-harness").is_file())
        self.assertEqual((self.root / "share/harness-versions.json").read_text(), versions)

    def test_unexpected_privileged_group_stops_before_authorizing_login(self):
        home = self.root / "tester"
        account = SimpleNamespace(pw_uid=1002, pw_gid=1002, pw_dir=str(home))
        with patch.object(users, "HOME_ROOT", self.root), \
             patch.object(users.pwd, "getpwnam", side_effect=[KeyError, account]), \
             patch.object(users.os, "getgrouplist", return_value=[1002, 10]), \
             patch.object(users, "run", side_effect=lambda *args: home.mkdir()):
            with self.assertRaisesRegex(ValueError, "unexpected UID or groups"):
                users.create("tester", self.public)
        self.assertFalse((home / ".ssh/authorized_keys").exists())


if __name__ == "__main__":
    unittest.main()
