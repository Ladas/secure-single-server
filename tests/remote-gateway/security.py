#!/usr/bin/env python3
"""Offline regressions for TLS negative-test assertions; no container required."""
import importlib.util
from pathlib import Path
import ssl
import unittest
import urllib.error
from unittest.mock import Mock, MagicMock

spec = importlib.util.spec_from_file_location("remote_image", Path(__file__).with_name("image.py"))
image = importlib.util.module_from_spec(spec)
spec.loader.exec_module(image)


class TlsAssertionsTest(unittest.TestCase):
    def test_certificate_verification_failure_is_the_only_pass(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.URLError(ssl.SSLCertVerificationError("untrusted"))
        image.expect_certificate_rejection(opener, "https://gateway.invalid")

    def test_http_denial_or_unrelated_transport_failure_cannot_pass(self):
        failures = [urllib.error.HTTPError("https://gateway.invalid", 401, "Unauthorized", {}, None),
                    urllib.error.URLError(ConnectionRefusedError("refused")),
                    urllib.error.URLError(TimeoutError("timed out"))]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                opener = Mock()
                opener.open.side_effect = failure
                with self.assertRaises(AssertionError):
                    image.expect_certificate_rejection(opener, "https://gateway.invalid")

    def test_successful_tls_cannot_pass(self):
        opener = Mock()
        opener.open.return_value = MagicMock()
        with self.assertRaises(AssertionError):
            image.expect_certificate_rejection(opener, "https://gateway.invalid")


if __name__ == "__main__":
    unittest.main()
