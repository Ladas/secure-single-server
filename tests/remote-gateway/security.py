#!/usr/bin/env python3
"""Offline gateway lifecycle and TLS assertion regressions; no container required."""
import importlib.util
from pathlib import Path
import ssl
import unittest
import urllib.error
from unittest.mock import Mock, MagicMock, call, patch

spec = importlib.util.spec_from_file_location("remote_image", Path(__file__).with_name("image.py"))
image = importlib.util.module_from_spec(spec)
spec.loader.exec_module(image)


class GatewayLifecycleTest(unittest.TestCase):
    def test_restart_reads_current_published_port(self):
        with patch.object(image, "run", side_effect=["gateway", "127.0.0.1:49161"]) as run:
            self.assertEqual(image.restart_gateway("gateway"), "49161")
        self.assertEqual(run.call_args_list, [call(image.ENGINE, "restart", "gateway"),
                                             call(image.ENGINE, "port", "gateway", "8443/tcp")])

    def test_readiness_retries_transient_failures_until_unauthenticated_denial(self):
        request = Mock(side_effect=[urllib.error.URLError(ConnectionRefusedError("refused")), 503, 401])
        with patch.object(image.time, "sleep") as sleep:
            image.wait_for_gateway(request, attempts=3)
        self.assertEqual(request.call_args_list, [call("/v1/models", method="GET")] * 3)
        self.assertEqual(sleep.call_args_list, [call(1)] * 2)

    def test_readiness_timeout_fails_instead_of_continuing_to_quota_assertions(self):
        request = Mock(side_effect=urllib.error.URLError(ConnectionRefusedError("refused")))
        with patch.object(image.time, "sleep") as sleep:
            with self.assertRaisesRegex(AssertionError, "TLS/JWT endpoint did not become ready.*refused"):
                image.wait_for_gateway(request, attempts=2)
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_readiness_requires_401_not_just_a_responding_server(self):
        for status in (200, 403, 404, 429, 500):
            with self.subTest(status=status), patch.object(image.time, "sleep"):
                request = Mock(return_value=status)
                with self.assertRaisesRegex(AssertionError, f"HTTP {status}"):
                    image.wait_for_gateway(request, attempts=2)

    def test_readiness_does_not_retry_certificate_verification_errors(self):
        certificate_error = ssl.SSLCertVerificationError("untrusted")
        for error in (certificate_error, urllib.error.URLError(certificate_error)):
            with self.subTest(error=type(error).__name__), patch.object(image.time, "sleep") as sleep:
                request = Mock(side_effect=error)
                with self.assertRaises(type(error)):
                    image.wait_for_gateway(request, attempts=2)
                request.assert_called_once_with("/v1/models", method="GET")
                sleep.assert_not_called()


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
