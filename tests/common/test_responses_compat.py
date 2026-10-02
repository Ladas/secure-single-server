"""Contracts for the isolated vLLM Responses portability experiment."""
import copy
import importlib.util
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'rhel/responses_compat.py'
spec = importlib.util.spec_from_file_location('responses_compat', SOURCE)
compat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compat)
MODEL = 'vllm/qwen'


def body(items, **extra):
    return json.dumps({'model': MODEL, 'input': items, **extra}).encode()


class HistoryPolicyTest(unittest.TestCase):
    def transform(self, payload, path='/v1/responses', method='POST'):
        return compat.transform(method, path, payload, {MODEL})

    def test_missing_type_normalized_without_changing_content_or_order(self):
        message = {'role': 'assistant', 'content': [
            {'type': 'output_text', 'text': 'one'}, {'type': 'output_text', 'text': 'two'}]}
        source = body([{'role': 'user', 'content': 'start'}, message])
        output, changes = self.transform(source)
        expected = json.loads(source)
        expected['input'][1]['type'] = 'message'
        self.assertEqual(json.loads(output), expected)
        self.assertEqual(changes, {'normalized_messages': 1, 'omitted_reasoning': 0})

    def test_only_encrypted_reasoning_removed_and_tools_remain_paired(self):
        items = [
            {'role': 'user', 'content': 'add'},
            {'type': 'reasoning', 'id': 'rs_foreign', 'summary': [], 'encrypted_content': 'opaque'},
            {'type': 'function_call', 'id': 'fc_a', 'call_id': 'call_a', 'name': 'add', 'arguments': '{}'},
            {'type': 'function_call_output', 'call_id': 'call_a', 'output': '5'},
            {'type': 'reasoning', 'id': 'rs_local', 'summary': [],
             'content': [{'type': 'reasoning_text', 'text': 'visible local reasoning'}]},
            {'type': 'message', 'id': 'msg_a', 'status': 'completed', 'role': 'assistant',
             'content': [{'type': 'output_text', 'text': '5', 'annotations': []}]},
        ]
        source = body(items, store=False, include=['reasoning.encrypted_content'])
        original = copy.deepcopy(items)
        output, changes = self.transform(source)
        expected = json.loads(source)
        expected['input'].pop(1)
        self.assertEqual(json.loads(output), expected)
        self.assertEqual(items, original)
        self.assertEqual(changes, {'normalized_messages': 0, 'omitted_reasoning': 1})
        self.assertEqual(self.transform(output), (output, {}), 'policy must be idempotent')

    def test_cloud_other_paths_and_methods_are_byte_preserving(self):
        local = body([{'type': 'reasoning', 'encrypted_content': 'opaque'}])
        cloud = local.replace(b'vllm/qwen', b'openai/model')
        self.assertEqual(self.transform(cloud), (cloud, {}))
        for path in ('/v1/messages', '/v1/chat/completions', '/v1/responses/compact', '/v1/responses?x=1'):
            self.assertEqual(self.transform(local, path), (local, {}))
        self.assertEqual(self.transform(local, method='GET'), (local, {}))

    def test_plain_inputs_and_existing_metadata_are_preserved(self):
        for items in ('hello', [{'role': 'assistant', 'content': 'hello'}],
                      [{'type': 'message', 'role': 'assistant', 'id': 'msg_existing',
                        'status': 'in_progress', 'content': [{'type': 'output_text', 'text': 'hello'}]}],
                      [{'role': 'assistant', 'content': [{'type': 'input_text', 'text': 'hello'}]}]):
            source = body(items)
            self.assertEqual(self.transform(source), (source, {}))

    def test_opaque_compaction_cannot_be_silently_discarded(self):
        for kind in ('compaction', 'compaction_summary', 'context_compaction'):
            with self.subTest(kind=kind), self.assertRaisesRegex(compat.UnportableHistory, 'compaction'):
                self.transform(body([{'type': kind, 'encrypted_content': 'opaque'}]))

    def test_provider_local_references_cannot_be_forwarded_as_visible_history(self):
        for field in ('previous_response_id', 'conversation'):
            with self.subTest(field=field), self.assertRaises(compat.UnportableHistory):
                self.transform(body('continue', **{field: 'foreign-id'}))
        with self.assertRaises(compat.UnportableHistory):
            self.transform(body([{'type': 'item_reference', 'id': 'foreign-id'}]))

    def test_malformed_json_is_left_to_praxis(self):
        for source in (b'broken', b'[]', b'{"model":null}', b'{"model":{}}'):
            self.assertEqual(self.transform(source), (source, {}))

    def test_encrypted_text_inside_user_content_is_untouched(self):
        source = body([{'role': 'user', 'content': 'explain encrypted_content'},
                       {'type': 'function_call_output', 'call_id': 'call_a',
                        'output': '{"encrypted_content":"fixture"}'}])
        self.assertEqual(self.transform(source), (source, {}))


class TransportTest(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.release = threading.Event()
        owner = self

        class Upstream(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *_args):
                pass

            def do_POST(self):
                payload = self.rfile.read(int(self.headers['Content-Length']))
                owner.requests.append((dict(self.headers), payload))
                if self.path == '/stream':
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.send_header('Transfer-Encoding', 'chunked')
                    self.end_headers()
                    chunk = b'data: first\n\n'
                    self.wfile.write(b'%x\r\n' % len(chunk) + chunk + b'\r\n')
                    self.wfile.flush()
                    owner.release.wait(5)
                    self.wfile.write(b'0\r\n\r\n')
                    return
                self.send_response(429 if self.path == '/denied' else 200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(payload)))
                self.send_header('Retry-After', '12')
                self.send_header('Connection', 'close, X-Internal')
                self.send_header('X-Internal', 'do not forward')
                self.end_headers()
                self.wfile.write(payload)

        self.upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        self.adapter = compat.make_server(0, self.upstream.server_port, {MODEL})
        self.threads = []
        for server in (self.upstream, self.adapter):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.threads.append(thread)

    def tearDown(self):
        self.release.set()
        for server in (self.adapter, self.upstream):
            server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join()

    def client(self):
        connection = http.client.HTTPConnection('127.0.0.1', self.adapter.server_port, timeout=2)
        self.addCleanup(connection.close)
        return connection

    def test_rewrites_length_and_preserves_auth_and_tools(self):
        source = body([{'type': 'reasoning', 'encrypted_content': 'opaque'},
                       {'type': 'function_call_output', 'call_id': 'a', 'output': 'ok'}])
        client = self.client()
        client.request('POST', '/v1/responses', source, headers={
            'Authorization': 'Bearer test-placeholder', 'Connection': 'X-Drop', 'X-Drop': 'private'})
        response = client.getresponse()
        output = response.read()
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(output)['input'], json.loads(source)['input'][1:])
        headers, sent = self.requests[0]
        self.assertEqual(int(headers['Content-Length']), len(sent))
        self.assertEqual(headers['Authorization'], 'Bearer test-placeholder')
        self.assertNotIn('X-Drop', headers)
        self.assertIsNone(response.getheader('X-Internal'))

    def test_cloud_body_status_and_retry_header_pass_through(self):
        source = body([{'type': 'reasoning', 'encrypted_content': 'opaque'}]).replace(
            b'vllm/qwen', b'openai/model')
        client = self.client()
        client.request('POST', '/denied', source)
        response = client.getresponse()
        self.assertEqual(response.status, 429)
        self.assertEqual(response.getheader('Retry-After'), '12')
        self.assertEqual(response.read(), source)

    def test_stream_is_forwarded_before_upstream_finishes(self):
        client = self.client()
        client.request('POST', '/stream', b'{}')
        response = client.getresponse()
        self.assertEqual(response.getheader('Content-Type'), 'text/event-stream')
        self.assertIsNone(response.getheader('Transfer-Encoding'))
        self.assertEqual(response.read(len(b'data: first\n\n')), b'data: first\n\n')
        self.assertFalse(self.release.is_set(), 'stream must arrive before upstream closes')
        self.release.set()
        self.assertEqual(response.read(), b'')

    def test_compaction_rejected_without_calling_praxis(self):
        client = self.client()
        client.request('POST', '/v1/responses', body([{'type': 'compaction', 'encrypted_content': 'opaque'}]))
        response = client.getresponse()
        self.assertEqual(response.status, 400)
        self.assertIn(b'compaction', response.read())
        self.assertEqual(self.requests, [])

    def test_oversized_body_rejected_before_reading(self):
        client = self.client()
        client.request('POST', '/v1/responses', b'', headers={'Content-Length': str(compat.MAX_BODY + 1)})
        response = client.getresponse()
        self.assertEqual(response.status, 413)
        response.read()
        self.assertEqual(self.requests, [])


if __name__ == '__main__':
    unittest.main()
