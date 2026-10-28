"""Private Unix-socket transport for the deployment-owned configuration adapter.

There is no TCP listener. A dedicated capability secret authenticates PriceTag;
ordinary browser/user credentials are never accepted here.
"""
import hmac
from http.server import BaseHTTPRequestHandler
import json
import socket
import socketserver
import threading

from gateway_management import Conflict

MAX_REQUEST = 256 * 1024


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(10)
        super().setup()
        # Absolute parsing deadline: a slow peer cannot retain a worker by
        # sending another byte just before each socket inactivity timeout.
        self.deadline = threading.Timer(self.server.request_timeout, self.expire)
        self.deadline.daemon = True
        self.deadline.start()

    def expire(self):
        try:
            self.request.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def handle(self):
        try:
            super().handle()
        except (OSError, TimeoutError):
            pass  # Peer disconnects/timeouts must not produce request dumps.
        finally:
            self.deadline.cancel()

    def log_message(self, *_):
        # Never log credentials, provider keys, request bodies or query strings.
        pass

    def respond(self, status, body):
        encoded = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def dispatch(self):
        supplied = self.headers.get('Authorization', '')
        expected = 'Bearer ' + self.server.credential
        if not hmac.compare_digest(supplied.encode(), expected.encode()):
            self.respond(401, {'error': 'unauthorized'})
            return
        if (self.path not in ('/config', '/discover') or
                (self.command, self.path) not in (('GET', '/config'), ('PUT', '/config'), ('POST', '/discover'))):
            self.respond(404, {'error': 'unknown operation'})
            return
        if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) > 1:
            self.respond(400, {'error': 'invalid framing'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= MAX_REQUEST:
                raise ValueError()
            if self.command == 'GET' and length:
                raise ValueError()
            if self.command != 'GET' and not length:
                raise ValueError()
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError()
            payload = json.loads(raw) if length else None
        except (ValueError, OSError):
            self.respond(400, {'error': 'invalid bounded JSON request'})
            return
        self.deadline.cancel()
        try:
            result = self.server.engine(self.command, self.path, payload)
        except Conflict:
            self.respond(409, {'error': 'configuration changed; reload before saving'})
        except ValueError:
            self.respond(400, {'error': 'configuration rejected; review approved origins and model settings'})
        except Exception:
            self.respond(503, {'error': 'configuration operation failed; operator inspection required'})
        else:
            self.respond(200, result)

    do_GET = dispatch
    do_PUT = dispatch
    do_POST = dispatch


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    # Bound parser workers; retain a separate lock for engine operations. Slow
    # clients must not monopolize the accept loop or overlap activations.
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, path, credential, engine, *, max_workers=8, request_timeout=10):
        if not isinstance(credential, str) or len(credential) < 32:
            raise ValueError('a dedicated high-entropy capability is required')
        if max_workers < 1 or request_timeout <= 0:
            raise ValueError('positive worker count and request timeout required')
        self.credential = credential
        self.request_timeout = request_timeout
        self.workers = threading.BoundedSemaphore(max_workers)
        self.engine_lock = threading.Lock()
        def serialized(*args):
            with self.engine_lock:
                return engine(*args)
        self.engine = serialized
        super().__init__(path, Handler)

    def process_request(self, request, client_address):
        if not self.workers.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.workers.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.workers.release()
