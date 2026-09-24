#!/usr/bin/env python3
"""Offline checks: generated keys/tokens never leave the temporary directory."""

import base64
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "scripts/remote-gateway/credentials"


class CredentialsTest(unittest.TestCase):
    def call(self, *args, ok=True):
        result = subprocess.run([str(TOOL), *map(str, args)], capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, ok, result.stderr)
        return result

    def test_key_token_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            keys = Path(directory) / "issuer"
            self.call("init-jwt", "--directory", keys)
            self.assertEqual((keys / "private.pem").stat().st_mode & 0o777, 0o600)
            self.call("init-jwt", "--directory", keys, ok=False)
            token = Path(directory) / "alice.jwt"
            self.call("issue", "--key", keys / "private.pem", "--subject", "alice",
                      "--output", token, "--days", "1")
            header, claims, signature = token.read_text().strip().split(".")
            payload = json.loads(base64.urlsafe_b64decode(claims + "=="))
            self.assertEqual(payload["sub"], "alice")
            self.assertEqual(payload["exp"] - payload["iat"], 86400)
            self.assertEqual(token.stat().st_mode & 0o777, 0o600)
            message = Path(directory) / "message"
            message.write_bytes(f"{header}.{claims}".encode())
            sig = Path(directory) / "signature"
            sig.write_bytes(base64.urlsafe_b64decode(signature + "=="))
            subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(keys / "public.pem"),
                            "-signature", str(sig), str(message)], check=True, capture_output=True)
            self.call("issue", "--key", keys / "private.pem", "--subject", "alice",
                      "--output", token, ok=False)
            self.call("issue", "--key", keys / "private.pem", "--subject", "alice",
                      "--output", Path(directory) / "bad.jwt", "--days", "0", ok=False)

    def test_lab_tls(self):
        with tempfile.TemporaryDirectory() as directory:
            tls = Path(directory) / "tls"
            self.call("lab-tls", "--directory", tls, "--hostname", "127.0.0.1")
            self.call("check-tls", "--cert", tls / "server.pem", "--key", tls / "server-key.pem")
            self.call("check-tls", "--cert", tls / "server.pem", "--key", tls / "ca-key.pem", ok=False)
            (tls / "server-key.pem").chmod(0o644)
            self.call("check-tls", "--cert", tls / "server.pem", "--key", tls / "server-key.pem", ok=False)
            self.call("lab-tls", "--directory", tls, "--hostname", "localhost", ok=False)
            self.call("lab-tls", "--directory", Path(directory) / "bad",
                      "--hostname", "example.com\nDNS:evil", ok=False)
            self.assertEqual((tls / "ca-key.pem").stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
