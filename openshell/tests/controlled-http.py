#!/usr/bin/env python3
"""Credential-free policy fixture: each reached request increments a private counter."""
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import sys
counter = Path(sys.argv[1])
class Handler(BaseHTTPRequestHandler):
    def _controlled(self):
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
HTTPServer((sys.argv[2], 18080), Handler).serve_forever()
