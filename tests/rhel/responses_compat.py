#!/usr/bin/env python3
"""Loopback-only Responses portability experiment; not a production gateway.

Native harness -> this adapter -> existing Praxis listener -> upstream.
No credentials are loaded and only explicitly selected local models are changed.
Run with --help. Stop the process after testing; normal harness configs stay intact.
"""
import argparse
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json

MAX_BODY = 10 * 1024 * 1024
HOP_HEADERS = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
               'te', 'trailer', 'transfer-encoding', 'upgrade'}


class UnportableHistory(ValueError):
    """History contains opaque provider state that cannot be safely normalized."""


def transform(method, path, payload, models):
    """Return (request bytes, change counts), preserving other requests byte for byte."""
    if method != 'POST' or path != '/v1/responses':
        return payload, {}
    try:
        request = json.loads(payload)
    except (ValueError, UnicodeError):
        return payload, {}
    if not isinstance(request, dict):
        return payload, {}
    model = request.get('model')
    if not isinstance(model, str) or model not in models:
        return payload, {}
    for field in ('previous_response_id', 'conversation'):
        if request.get(field):
            raise UnportableHistory('Local vLLM needs explicit message/tool history, not ' + field)
    items = request.get('input')
    if not isinstance(items, list):
        return payload, {}
    changes = {'normalized_messages': 0, 'omitted_reasoning': 0}
    kept = []
    for item in items:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        kind = item.get('type')
        if kind in ('compaction', 'compaction_summary', 'context_compaction'):
            raise UnportableHistory('Opaque compaction cannot be transferred to local vLLM; '
                                    'start a new session with an explicit summary')
        if kind == 'item_reference':
            raise UnportableHistory('Local vLLM cannot resolve provider-local item_reference')
        if kind == 'reasoning' and item.get('encrypted_content'):
            changes['omitted_reasoning'] += 1
            continue
        content = item.get('content')
        if ('type' not in item and item.get('role') == 'assistant'
                and isinstance(content, list) and content
                and all(isinstance(part, dict) and part.get('type') == 'output_text'
                        for part in content)):
            item['type'] = 'message'
            changes['normalized_messages'] += 1
        kept.append(item)
    if not any(changes.values()):
        return payload, {}
    request['input'] = kept
    return json.dumps(request, separators=(',', ':')).encode(), changes


def forwarded_headers(headers, omit=()):
    """Remove hop-by-hop headers, including names declared by Connection."""
    excluded = HOP_HEADERS | set(omit)
    for value in headers.get_all('Connection', []):
        excluded.update(word.strip().lower() for word in value.split(','))
    return [(key, value) for key, value in headers.items() if key.lower() not in excluded]


def make_server(port, upstream_port, models, audit_limits=False):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *_args):
            # Do not log paths, bodies, credentials or conversation content.
            pass

        def error(self, status, message):
            data = json.dumps({'error': {'type': 'invalid_request_error',
                                        'message': message}}).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.close_connection = True
            self.wfile.write(data)

        def proxy(self):
            self.connection.settimeout(300)
            if not self.path.startswith('/') or self.path.startswith('//'):
                self.error(400, 'Only origin-form local gateway paths are supported')
                return
            lengths = self.headers.get_all('Content-Length', [])
            if self.headers.get('Transfer-Encoding') or len(lengths) > 1:
                self.error(400, 'Send a single Content-Length; chunked requests are unsupported')
                return
            try:
                if lengths and not lengths[0].strip().isdigit():
                    raise ValueError
                length = int(lengths[0]) if lengths else 0
            except ValueError:
                self.error(400, 'Invalid Content-Length')
                return
            if length > MAX_BODY:
                self.error(413, 'Experiment request body exceeds 10 MiB')
                return
            if self.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                self.error(415, 'Experiment requires an uncompressed request body')
                return
            started = False
            upstream = http.client.HTTPConnection('127.0.0.1', upstream_port, timeout=300)
            try:
                body = self.rfile.read(length)
                if len(body) != length:
                    self.error(400, 'Incomplete request body')
                    return
                try:
                    body, changes = transform(self.command, self.path, body, models)
                except UnportableHistory as error:
                    self.error(400, str(error))
                    return
                if changes:
                    print(json.dumps(changes), flush=True)
                if audit_limits:
                    try:
                        request = json.loads(body)
                    except (ValueError, UnicodeError):
                        request = None
                    if isinstance(request, dict):
                        # Synthetic test metadata only. Never log bodies or headers.
                        print(json.dumps({'request_limits': {
                            key: request.get(key) for key in ('model', 'max_tokens', 'max_output_tokens')
                            if key == 'model' and isinstance(request.get(key), str)
                            or key != 'model' and type(request.get(key)) is int}}), flush=True)
                upstream.putrequest(self.command, self.path, skip_host=True, skip_accept_encoding=True)
                for key, value in forwarded_headers(self.headers, ('host', 'content-length', 'expect')):
                    upstream.putheader(key, value)
                upstream.putheader('Host', '127.0.0.1:' + str(upstream_port))
                upstream.putheader('Content-Length', str(len(body)))
                upstream.putheader('Connection', 'close')
                upstream.endheaders(body)
                response = upstream.getresponse()
                self.send_response(response.status, response.reason)
                for key, value in forwarded_headers(response.headers, ('server', 'date')):
                    self.send_header(key, value)
                self.send_header('Connection', 'close')
                self.end_headers()
                self.close_connection = True
                started = True
                while True:
                    chunk = response.read1(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (OSError, http.client.HTTPException):
                if not started:
                    self.error(502, 'Experiment could not complete the local Praxis request')
            finally:
                self.close_connection = True
                upstream.close()

        do_GET = proxy
        do_POST = proxy

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=18180)
    parser.add_argument('--upstream-port', type=int, default=8080)
    parser.add_argument('--model', action='append', required=True, help='Exact local vLLM alias; repeatable')
    parser.add_argument('--audit-limits', action='store_true', help='Log model and output-cap fields only')
    args = parser.parse_args()
    if not all(1 <= port <= 65535 for port in (args.port, args.upstream_port)):
        parser.error('ports must be between 1 and 65535')
    if args.port == args.upstream_port:
        parser.error('experiment and upstream ports must differ')
    if any(not model.startswith('vllm/') for model in args.model):
        parser.error('this experiment only supports explicit vllm/ model aliases')
    with make_server(args.port, args.upstream_port, set(args.model), args.audit_limits) as server:
        print('Responses compatibility experiment listening on 127.0.0.1:' + str(args.port), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
