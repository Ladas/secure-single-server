#!/usr/bin/env python3
"""External qualification must reject local endpoints, stale evidence and leaked credentials."""
import importlib.util
import json
import os
import hashlib
import errno
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import subprocess
import socket
import ssl
import tempfile
import time
import threading
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("remote_client", Path(__file__).with_name("run.py"))
client = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = client
spec.loader.exec_module(client)


class RemoteTest(unittest.TestCase):
    def test_interruption_stops_the_harness_process_group(self):
        with patch.object(client.subprocess.Popen, "communicate", side_effect=[KeyboardInterrupt(), ("", "")]), \
             patch.object(client.os, "killpg", wraps=os.killpg) as killed:
            with self.assertRaises(KeyboardInterrupt):
                client.run_captured([sys.executable, "-c", "import time; time.sleep(60)"], timeout=1)
            killed.assert_called()

    def test_only_external_https_origins_are_accepted(self):
        self.assertEqual(client.origin("https://gateway.example:8443/"), "https://gateway.example:8443")
        for value in ("http://gateway.example:8443", "https://localhost:8443", "https://127.0.0.1:8443",
                      "https://[::1]:8443", "https://0.0.0.0:8443", "https://[::]:8443",
                      "https://user:secret@gateway.example", "https://gateway.example/v1",
                      "https://gateway.example?token=private", "https://gateway.example#fragment"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                client.origin(value)

    def test_server_identity_recency_and_runtime_must_match(self):
        evidence = {"scenario": "remote-gateway", "collected_at": time.time(), "machine_id_sha256": "server",
                    "url": "https://gateway.example:8443", "mock": False, "inference": "cpu",
                    "model": "qwen3.8-27b-int4", "context_tokens": 32768, "backend_ports_private": True}
        with patch.object(client, "machine_id", return_value="client"):
            client.validate_server(evidence, evidence["url"], "real", "vllm", evidence["model"])
            for key, wrong in (("machine_id_sha256", "client"), ("collected_at", 0), ("mock", True),
                               ("context_tokens", 16384), ("backend_ports_private", False), ("inference", "none")):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    client.validate_server({**evidence, key: wrong}, evidence["url"], "real", "vllm", evidence["model"])

    def test_client_environment_does_not_inherit_upstream_keys_or_personal_config(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(client.os.environ, {
                "OPENAI_API_KEY": "private-openai", "ANTHROPIC_API_KEY": "private-anthropic",
                "OPENCODE_CONFIG_CONTENT": "personal", "CLAUDE_CODE_USE_BEDROCK": "1", "HTTP_PROXY": "private"}):
            root = Path(directory)
            env = client.client_environment(root)
            self.assertEqual(env["HOME"], str(root))
            self.assertEqual(env["CODEX_HOME"], str(root / "codex"))
            for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENCODE_CONFIG_CONTENT", "CLAUDE_CODE_USE_BEDROCK", "HTTP_PROXY"):
                self.assertNotIn(name, env)

    def test_evidence_redacts_every_caller_credential(self):
        text = 'failed: Bearer first.caller.signature second.caller.signature'
        self.assertEqual(client.redact(text, ["first.caller.signature", "second.caller.signature"]),
                         'failed: Bearer [caller] [caller]')

    def test_generated_tests_do_not_replace_independent_function_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "add.py").write_text("def add(a,b): return 5\n")
            (root / "test_add.py").write_text("import unittest\nclass Test(unittest.TestCase):\n def test_fake(self): self.assertTrue(True)\n")
            with self.assertRaises(AssertionError):
                client.verify_project(root, client.client_environment(root))
            (root / "add.py").write_text("def add(a,b): return a+b\n")
            client.verify_project(root, client.client_environment(root))


class TransportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="praxis-remote-unit-")
        cls.root = Path(cls.temporary.name)
        tool = client.ROOT / "scripts/remote-gateway/credentials"
        subprocess.run([str(tool), "lab-tls", "--directory", str(cls.root / "tls"), "--hostname", "localhost"],
                       check=True, capture_output=True)
        subprocess.run([str(tool), "init-jwt", "--directory", str(cls.root / "issuer")], check=True, capture_output=True)
        cls.redirect_followed = False

        class Handler(BaseHTTPRequestHandler):
            def handle(self):
                try:
                    super().handle()
                except (ConnectionResetError, BrokenPipeError):
                    pass  # Certificate probes intentionally close without an HTTP request.

            def log_message(self, *_):
                pass

            def do_GET(self):
                if self.path.endswith("/redirect"):
                    self.send_response(302)
                    self.send_header("Location", "/destination")
                    self.end_headers()
                    return
                if self.path == "/destination":
                    cls.redirect_followed = True
                valid = self.headers.get("Authorization") == "Bearer synthetic-caller"
                payload = json.dumps({"data": [{"id": "fixture"}]}).encode()
                self.send_response(200 if valid else 401)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cls.root / "tls/server.pem", cls.root / "tls/server-key.pem")
        cls.server.socket = context.wrap_socket(cls.server.socket, server_side=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temporary.cleanup()

    def remote(self):
        return client.Remote(f"https://localhost:{self.server.server_port}", self.root / "tls/ca.pem",
                             "synthetic-caller", "vllm", "fixture", False)

    def test_verified_https_and_caller_authentication(self):
        remote = self.remote()
        self.assertEqual(remote.request("/v1/models", method="GET")[0], 200)
        self.assertEqual(remote.request("/v1/models", method="GET", token="")[0], 401)

    def test_redirects_are_refused_before_forwarding_caller(self):
        with self.assertRaisesRegex(ValueError, "redirect"):
            self.remote().request("/redirect", method="GET")
        self.assertFalse(self.redirect_followed)

    def test_tls_and_port_probe_requires_trust_and_backend_isolation(self):
        fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert((self.root / "tls/server.pem").read_text())).hexdigest()
        connect = socket.create_connection
        def private(address, **kwargs):
            if address[1] in client.BACKEND_PORTS:
                raise ConnectionRefusedError()
            return connect(address, **kwargs)
        with patch.object(client.socket, "create_connection", side_effect=private):
            self.remote().tls_and_ports(fingerprint)
        def broken(address, **kwargs):
            if address[1] in client.BACKEND_PORTS:
                raise OSError(errno.EMFILE, "no file descriptors")
            return connect(address, **kwargs)
        with patch.object(client.socket, "create_connection", side_effect=broken), self.assertRaises(OSError):
            self.remote().tls_and_ports(fingerprint)
        with self.assertRaisesRegex(AssertionError, "certificate differs"):
            self.remote().tls_and_ports("different-certificate")

    def test_issuer_creates_private_distinct_and_expired_callers_without_copying_key(self):
        destination = self.root / "issued-callers"
        command = [sys.executable, str(Path(__file__).with_name("issue.py")),
                   "--key", str(self.root / "issuer/private.pem"), "--output", str(destination)]
        subprocess.run(command, check=True, capture_output=True)
        self.assertEqual(destination.stat().st_mode & 0o777, 0o700)
        self.assertEqual({p.name for p in destination.iterdir()}, {"caller.jwt", "second.jwt", "expired.jwt"})
        subjects = set()
        public = (self.root / "issuer/public.pem").read_text()
        for path in destination.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            claims = client.verified_claims(path.read_text().strip(), public, expired=path.name == "expired.jwt")
            subjects.add(claims["sub"])
        self.assertEqual(len(subjects), 3)
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)

    def test_expired_token_must_be_correctly_signed(self):
        from gateway import token
        public = (self.root / "issuer/public.pem").read_text()
        valid = token(self.root / "issuer/private.pem")
        self.assertEqual(client.verified_claims(valid, public)["sub"], "test-user")
        expired = token(self.root / "issuer/private.pem", exp=int(time.time()) - 600)
        client.verified_claims(expired, public, expired=True)
        with self.assertRaises(ValueError):
            client.verified_claims(expired, public)
        left, signature = expired.rsplit(".", 1)
        corrupt = left + "." + ("A" if signature[0] != "A" else "B") + signature[1:]
        with self.assertRaisesRegex(ValueError, "signature"):
            client.verified_claims(corrupt, public, expired=True)


if __name__ == "__main__":
    unittest.main()
