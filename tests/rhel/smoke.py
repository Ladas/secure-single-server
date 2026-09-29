#!/usr/bin/env python3
"""Offline checks for the RHEL smoke driver; never install anything on this host."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class SmokeTest(unittest.TestCase):
    def run_smoke(self, args, installed=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("tests/rhel", "scripts/common", "scripts/all-in-one", "scripts/remote-gateway"):
                (root / name).mkdir(parents=True)
            shutil.copyfile(ROOT / "tests/rhel/install-smoke.sh", root / "tests/rhel/install-smoke.sh")
            (root / "scripts/common/lib.sh").write_text('''
CONFIG_DIR="$REPO_DIR/config"
PROFILE_FILE="$CONFIG_DIR/profile"
MANIFEST_FILE="$CONFIG_DIR/manifest"
SCENARIO_FILE="$CONFIG_DIR/scenario"
die() { printf 'error: %s\\n' "$*" >&2; exit 1; }
require_root() { :; }
require_command() { :; }
''')
            for name in ("all-in-one/install", "remote-gateway/install", "common/secret-set",
                         "common/status", "common/verify", "remote-gateway/credentials"):
                path = root / "scripts" / name
                path.write_text('''#!/usr/bin/env bash
printf '%s %s\\n' "${0##*/}" "$*" >> "$SMOKE_CALLS"
if [[ "${0##*/}" == secret-set && "$*" != *--generate ]]; then cat >/dev/null; fi
''')
                path.chmod(0o755)
            if installed:
                (root / "config").mkdir()
                (root / "config/manifest").touch()
            result = subprocess.run(["bash", str(root / "tests/rhel/install-smoke.sh"), *args],
                                    env={**os.environ, "SMOKE_CALLS": str(root / "calls")},
                                    capture_output=True, text=True, timeout=10)
            calls = (root / "calls").read_text() if (root / "calls").exists() else ""
            return result, calls

    def test_invalid_arguments_never_prepare_host(self):
        for args in ([], ["typo", "memory"], ["all-in-one", "typo"],
                     ["remote-gateway", "memory"], ["all-in-one", "memory", "extra"]):
            with self.subTest(args=args):
                result, calls = self.run_smoke(args)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, "")

    def test_existing_or_partial_install_is_preserved(self):
        result, calls = self.run_smoke(["all-in-one", "memory"], installed=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("existing", result.stderr)
        self.assertEqual(calls, "")

    def test_memory_install_uses_only_synthetic_credentials_and_host_checks(self):
        result, calls = self.run_smoke(["all-in-one", "memory"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("install --prepare", calls)
        self.assertIn("--profile memory", calls)
        self.assertIn("--openai-secret praxis-openai-api-key-smoke-", calls)
        self.assertIn("--anthropic-secret praxis-anthropic-api-key-smoke-", calls)
        self.assertNotIn("--replace", calls)
        self.assertIn("verify --host", calls)
        self.assertIn("inference has not been tested", result.stdout)

    def test_valkey_installs_generated_credentials_and_pinned_image(self):
        result, calls = self.run_smoke(["all-in-one", "valkey"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--generate", calls)
        self.assertIn("--valkey-image docker.io/valkey/valkey@sha256:", calls)
        self.assertIn("--valkey-url-secret praxis-valkey-url-smoke-", calls)
        self.assertIn("--valkey-acl-secret praxis-valkey-acl-smoke-", calls)

    def test_remote_material_required_before_preparation(self):
        result, calls = self.run_smoke(["remote-gateway", "memory", "/missing-material"])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, "")
        with tempfile.TemporaryDirectory() as directory:
            for filename in ("tls.pem", "tls-key.pem", "jwt-public.pem"):
                (Path(directory) / filename).write_text("synthetic")
            result, calls = self.run_smoke(["remote-gateway", "memory", directory])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--tls-cert", calls)
        self.assertIn("--tls-key", calls)
        self.assertIn("--jwt-public-key", calls)


if __name__ == "__main__":
    unittest.main()
