#!/usr/bin/env python3
"""Reachable HTTP errors must never be mistaken for network denials."""
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import json
import subprocess
import threading

class Handler(BaseHTTPRequestHandler):
    hits = 0
    def do_GET(self):
        Handler.hits += 1
        self.send_response(int(self.path[1:]))
        self.end_headers()
        self.wfile.write(b'reachable')
    def log_message(self, *args): pass

server = HTTPServer(('127.0.0.1', 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    for status in (200, 401, 403, 500):
        result = subprocess.run(['node', str(Path(__file__).with_name('probe.mjs')),
                                 f'http://127.0.0.1:{server.server_port}/{status}'],
                                capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert data == {'kind':'http','status':status,'body':'reachable'}, data
    assert Handler.hits == 4
finally:
    server.shutdown()
    server.server_close()
print('HTTP 200/401/403/500 reachability regression: OK')
