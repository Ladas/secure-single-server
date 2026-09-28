"""Contract tests for the fixture, independent of Praxis and container engines."""
import json
import unittest
import urllib.error
import urllib.request

from provider import Provider
from contracts import check


class ProviderTest(unittest.TestCase):
    def setUp(self):
        self.fixture = Provider(ports=(0, 0, 0))
        self.fixture.start()
        self.addCleanup(self.fixture.close)

    def request(self, path, body, provider=0, key=None):
        headers = {"Content-Type": "application/json"}
        if provider == 0:
            headers["Authorization"] = key or "Bearer synthetic-openai"
        else:
            headers["x-api-key"] = key or "synthetic-anthropic"
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.fixture.ports[provider]}{path}",
            json.dumps(body).encode(), headers)
        return urllib.request.urlopen(req, timeout=2)

    def test_json_streams_and_usage_for_each_protocol(self):
        for path in ("/v1/chat/completions", "/v1/responses", "/v1/messages"):
            for stream in (False, True):
                with self.subTest(path=path, stream=stream):
                    with self.request(path, {"model": "fixture", "stream": stream},
                                      provider=int(path == "/v1/messages")) as response:
                        body = response.read().decode()
                    self.assertIn("mock answer", body)
                    self.assertIn("usage", body)
                    check(path, body, stream)
                    if stream:
                        self.assertIn("text/event-stream", response.headers["Content-Type"])
                        self.assertIn("data: ", body)
                    else:
                        self.assertEqual(json.loads(body)["model"], "fixture")
        self.assertEqual(len(self.fixture.records), 6)
        self.assertTrue(all(record["credential_ok"] for record in self.fixture.records))

    def test_errors_and_missing_usage_are_controlled(self):
        for mode, status in (("http429", 429), ("http500", 500)):
            self.fixture.mode = mode
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.request("/v1/responses", {"model": "fixture"})
            self.assertEqual(caught.exception.code, status)
        self.fixture.mode = "missing_usage"
        with self.request("/v1/responses", {"model": "fixture"}) as response:
            self.assertNotIn("usage", json.load(response))

    def test_credentials_are_checked_without_recording_secrets(self):
        secret = "Bearer caller-secret-that-must-not-appear"
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/v1/responses", {"model": "fixture"}, key=secret)
        self.assertEqual(caught.exception.code, 403)
        self.assertFalse(self.fixture.records[0]["credential_ok"])
        self.assertNotIn(secret, json.dumps(self.fixture.records))

    def test_tool_result_is_required_for_continuation(self):
        with self.request("/v1/chat/completions", {"model": "fixture", "tools": [{}]}) as response:
            call = json.load(response)["choices"][0]["message"]["tool_calls"][0]
        self.assertEqual(call["function"]["arguments"], '{"a":2,"b":3}')
        with self.request("/v1/chat/completions", {"model": "fixture", "messages": [
            {"role": "tool", "tool_call_id": call["id"], "content": "5"}]}) as response:
            self.assertEqual(json.load(response)["choices"][0]["message"]["content"], "5")
        self.assertTrue(self.fixture.records[-1]["continuation"])


if __name__ == "__main__":
    unittest.main()
