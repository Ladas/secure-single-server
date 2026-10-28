#!/usr/bin/env python3
import http.client
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'scripts/pricetag'), str(ROOT / 'scripts/common')]
from gateway_management_transport import Server


class Transport(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / 'management.sock')
        self.calls = []
        def engine(method, path, body):
            self.calls.append((method, path, body))
            if body and body.get('fail'):
                raise ValueError('sensitive-provider-key-must-not-be-returned')
            return {'revision': 'fixture'}
        self.secret = 'test-only-capability-not-a-real-secret'
        self.server = Server(self.path, self.secret, engine)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.directory.cleanup()

    def request(self, method='GET', path='/config', body=None, credential=None):
        connection = http.client.HTTPConnection('unix', timeout=2)
        connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.sock.settimeout(2)
        connection.sock.connect(self.path)
        headers = {'Authorization': 'Bearer ' + (credential or self.secret)}
        connection.request(method, path, body=None if body is None else json.dumps(body), headers=headers)
        response = connection.getresponse()
        result = response.status, response.read(), response.getheader('Cache-Control')
        connection.close()
        return result

    def test_partial_headers_do_not_block_authenticated_client(self):
        peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        peer.connect(self.path)
        try:
            peer.sendall(b'GET /config HTTP/1.1\r\nHost: local\r\n')
            time.sleep(.1)
            self.assertEqual(self.request()[0], 200)
        finally:
            peer.close()

    def test_slow_headers_have_total_deadline(self):
        self.server.request_timeout = .3
        peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        peer.settimeout(1)
        peer.connect(self.path)
        try:
            peer.sendall(b'GET /config HTTP/1.1\r\nX-Slow: ')
            for _ in range(10):
                try:
                    peer.sendall(b'a')
                except OSError:
                    break
                time.sleep(.08)
            self.assertEqual(peer.recv(1), b'')
            self.assertEqual(self.calls, [])
            self.assertEqual(self.request()[0], 200)
        finally:
            peer.close()

    def test_worker_saturation_is_bounded_and_recovers(self):
        self.server.request_timeout = .5
        peers = []
        try:
            for _ in range(8):
                peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                peer.settimeout(1)
                peer.connect(self.path)
                peer.sendall(b'GET /config HTTP/1.1\r\nX-Slow: ')
                peers.append(peer)
            time.sleep(.1)
            extra = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            extra.settimeout(1)
            extra.connect(self.path)
            peers.append(extra)
            self.assertEqual(extra.recv(1), b'')
            time.sleep(.6)
            self.assertEqual(self.request()[0], 200)
        finally:
            for peer in peers:
                peer.close()

    def test_dedicated_credential_required_before_engine(self):
        status, _, cache = self.request(credential='user-inference-key')
        self.assertEqual(status, 401)
        self.assertEqual(cache, 'no-store')
        self.assertEqual(self.calls, [])

    def test_fixed_routes_only(self):
        for path in ['/config?file=/etc/shadow', '/shell', '/config/../config']:
            self.assertEqual(self.request(path=path)[0], 404)
        self.assertEqual(self.calls, [])

    def test_sanitized_failures_and_success(self):
        status, body, _ = self.request('PUT', '/config', {'fail': True})
        self.assertEqual(status, 400)
        self.assertNotIn(b'sensitive-provider-key', body)
        self.assertEqual(self.request()[0], 200)

    def test_large_body_rejected_without_engine(self):
        connection = http.client.HTTPConnection('unix', timeout=2)
        connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.sock.settimeout(2)
        connection.sock.connect(self.path)
        connection.putrequest('PUT', '/config')
        connection.putheader('Authorization', 'Bearer ' + self.secret)
        connection.putheader('Content-Length', '262145')
        connection.endheaders()
        response = connection.getresponse()
        self.assertEqual(response.status, 400)
        response.read()
        connection.close()
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
