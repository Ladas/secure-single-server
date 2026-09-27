"""A responding gateway, wrong credential, or forwarded 429 cannot fake a pass."""
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from evidence import save
from gateway import expect


class ForwardingAssertionsTest(unittest.TestCase):
    def test_quota_rejection_must_not_reach_provider(self):
        gateway = Mock()
        gateway.request.return_value = (429, "", {})
        gateway.records.side_effect = [[], [{"path": "/v1/responses"}]]
        with self.assertRaisesRegex(AssertionError, "request count"):
            expect(gateway, "/v1/responses", status=429, forwarded=False)

    def test_missing_forwarding_cannot_pass_with_canned_response(self):
        gateway = Mock()
        gateway.request.return_value = (200, '{"model":"fixture"}', {})
        gateway.records.return_value = []
        with self.assertRaisesRegex(AssertionError, "request count"):
            expect(gateway, "/v1/responses")

    def test_incorrect_credentials_classification_and_routing_fail(self):
        valid = {"path": "/v1/responses", "model": "fixture", "credential_ok": True,
                 "classification_clean": True}
        for changed in ({"credential_ok": False}, {"classification_clean": False},
                        {"path": "/v1/messages"}, {"model": "spoofed-model"}):
            with self.subTest(changed=changed):
                gateway = Mock()
                gateway.request.return_value = (200, "{}", {})
                gateway.records.side_effect = [[], [{**valid, **changed}]]
                with self.assertRaises(AssertionError):
                    expect(gateway, "/v1/responses")

    def test_evidence_remains_json_after_redaction(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", TEST_EVIDENCE_DIR=directory):
            save("fixture", {"logs": 'Authorization: Bearer other-secret\nx-api-key: secret-value',
                             "status": "failed"})
            text = (Path(directory) / "fixture.json").read_text()
            self.assertEqual(json.loads(text)["status"], "failed")
            self.assertNotIn("secret-value", text)
            self.assertNotIn("other-secret", text)


if __name__ == "__main__":
    unittest.main()
