#!/usr/bin/env python3
"""Credential-free policy fixture: each reached request increments a private counter."""
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import sys
counter = Path(sys.argv[1])
port = int(sys.argv[3]) if len(sys.argv) > 3 else 18080
class Handler(BaseHTTPRequestHandler):
    def _controlled(self):
        length = int(self.headers.get('Content-Length') or 0)
        if length:
            self.rfile.read(length)
        with counter.open('a') as output:
            output.write('request\n')
        self.send_response(401)
        self.end_headers()
        self.wfile.write(b'controlled-reachable-401')
    def do_GET(self):
        self._controlled()
    def do_POST(self):
        self._controlled()
    def do_DELETE(self):
        self._controlled()
    def log_message(self, *args): pass
HTTPServer((sys.argv[2], port), Handler).serve_forever()
