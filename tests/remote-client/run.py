#!/usr/bin/env python3
"""Run native harness acceptance on a separate client through HTTPS/CA/caller JWT."""
import argparse
import base64
import errno
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tests/rhel"), str(ROOT / "tests/common"), str(ROOT / "scripts/common")]
from integration import TASK, MARKER, ran_tests, run_captured, check_real_answer
from contracts import check
from harness import qwen_limits

BACKEND_PORTS = (8000, 8080, 8081, 9901, 6379, 19000, 19001)
HARNESSES = ("codex", "opencode", "claude")
BLOCKED_PAIRS = {
    ("openai", "claude"): "Messages-to-OpenAI API translation is not configured in this gateway/launcher",
    ("anthropic", "codex"): "Responses-to-Anthropic API translation is not configured in this gateway/launcher",
}


def harness_matrix(provider):
    return {name: ({"status": "blocked", "reason": BLOCKED_PAIRS[provider, name]}
                   if (provider, name) in BLOCKED_PAIRS else {"status": "not-run"}) for name in HARNESSES}


def origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("use an external HTTPS origin without credentials, path, query or fragment")
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("loopback is not an external-client test")
    try:
        address = ipaddress.ip_address(host)
        local = address.is_loopback or address.is_unspecified
    except ValueError:
        local = False
    if local:
        raise ValueError("loopback or unspecified addresses are not external-client tests")
    if parsed.port is not None and not 0 < parsed.port < 65536:
        raise ValueError("invalid gateway port")
    return value.rstrip("/")


def machine_id():
    path = Path("/etc/machine-id")
    identity = path.read_text().strip() if path.exists() else platform.system() + ":" + platform.node()
    return hashlib.sha256(identity.encode()).hexdigest()


def validate_server(record, url, mode, provider, model):
    if record.get("scenario") != "remote-gateway" or record.get("url") != url:
        raise ValueError("server evidence must describe this remote-gateway URL")
    age = time.time() - record.get("collected_at", 0)
    if not 0 <= age <= 3600:
        raise ValueError("collect server evidence within the last hour")
    if not record.get("machine_id_sha256") or record["machine_id_sha256"] == machine_id():
        raise ValueError("run harnesses on a separate client, not the gateway host")
    if record.get("mock") != (mode == "mock") or not record.get("backend_ports_private"):
        raise ValueError("server mode or backend isolation does not match qualification")
    if mode == "real":
        if provider != "vllm" or record.get("inference") not in ("cpu", "gpu") or record.get("model") != model:
            raise ValueError("real automation supports the recorded local CPU/GPU Qwen preset only")
        if record.get("context_tokens") != qwen_limits(model)[0]:
            raise ValueError("update the server and launcher together before testing their context limits")


def client_environment(home):
    # Keep personal CLI config, credentials and HTTP proxy settings out of the task.
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    for directory in ("codex", "claude", "config", "data", "cache"):
        (home / directory).mkdir(mode=0o700, exist_ok=True)
    return {"PATH": os.environ["PATH"], "HOME": str(home), "LANG": "C.UTF-8",
            "CODEX_HOME": str(home / "codex"), "CLAUDE_CONFIG_DIR": str(home / "claude"),
            "XDG_CONFIG_HOME": str(home / "config"), "XDG_DATA_HOME": str(home / "data"),
            "XDG_CACHE_HOME": str(home / "cache")}


def redact(text, tokens):
    for token in tokens:
        text = text.replace(token, "[caller]")
    return text


def private_write(path, text):
    with path.open("w") as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(text)


def verify_project(directory, environment):
    result = run_captured([sys.executable, "-m", "unittest", "-v"], cwd=directory, env=environment, timeout=30)
    assert result.returncode == 0 and "Ran 0 tests" not in result.stderr, "generated tests failed or were empty"
    result = run_captured([sys.executable, "-c",
        "from add import add; assert add(2,3)==5; assert add(-2,-3)==-5; assert add(0,0)==0; assert add(10,-3)==7"],
        cwd=directory, env=environment, timeout=30)
    assert result.returncode == 0, "independent function checks failed"


def verified_claims(token, public_key, *, expired=False):
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token):
        raise ValueError("caller file must contain one JWT")
    header, payload, signature = token.split(".")
    decode = lambda value: base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    claims = json.loads(decode(payload))
    if json.loads(decode(header)).get("alg") != "RS256" or not isinstance(claims.get("sub"), str):
        raise ValueError("expected the gateway's RS256 caller JWT with a subject")
    expires = claims.get("exp")
    if (type(expires) not in (int, float) or
            (expires > time.time() - 120 if expired else expires < time.time() + 60)):
        raise ValueError("caller expiration does not match this positive/expired test")
    with tempfile.TemporaryDirectory(prefix="praxis-jwt-check-") as directory:
        key, sig = Path(directory) / "public.pem", Path(directory) / "signature"
        key.write_text(public_key)
        sig.write_bytes(decode(signature))
        verified = subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(key), "-signature", str(sig)],
            input=(header + "." + payload).encode(), capture_output=True, timeout=10)
        if verified.returncode:
            raise ValueError("caller signature does not match the exported gateway public key")
    return claims


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("gateway redirects are refused; caller credentials must stay at the selected origin")


class Remote:
    def __init__(self, url, ca, token, provider, model, real):
        self.url, self.token, self.model, self.real = url, token, model, real
        self.prefix = "/vllm" if provider == "vllm" else ""
        self.context = ssl.create_default_context(cafile=str(ca))
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                                urllib.request.HTTPSHandler(context=self.context))
        self.last_request = 0

    def request(self, path, body=None, *, token=None, method="POST"):
        time.sleep(max(0, 0.65 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        selected = self.token if token is None else token
        headers = {"Content-Type": "application/json"}
        if selected:
            headers["Authorization"] = "Bearer " + selected
        request = urllib.request.Request(self.url + self.prefix + path,
            data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
        try:
            response = self.opener.open(request, timeout=600 if self.real else 30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.read().decode()

    def verify_tls(self, fingerprint):
        target = urlsplit(self.url)
        with socket.create_connection((target.hostname, target.port or 443), timeout=10) as raw:
            with self.context.wrap_socket(raw, server_hostname=target.hostname) as tls:
                assert hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest() == fingerprint, "gateway certificate differs from server evidence"
        # An empty trust store must reject the same endpoint, even with public PKI.
        untrusted = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        try:
            with socket.create_connection((target.hostname, target.port or 443), timeout=10) as raw:
                with untrusted.wrap_socket(raw, server_hostname=target.hostname):
                    pass
        except ssl.SSLCertVerificationError:
            pass
        else:
            raise AssertionError("untrusted gateway certificate was accepted")

    def tls_and_ports(self, fingerprint):
        self.verify_tls(fingerprint)
        target = urlsplit(self.url)
        for port in BACKEND_PORTS:
            try:
                connection = socket.create_connection((target.hostname, port), timeout=2)
            except (ConnectionRefusedError, TimeoutError, OSError) as error:
                if not isinstance(error, (ConnectionRefusedError, TimeoutError)) and error.errno not in (
                        errno.ECONNREFUSED, errno.ETIMEDOUT, errno.EHOSTUNREACH, errno.ENETUNREACH):
                    raise  # DNS/resource/permission failures do not prove isolation.
            else:
                connection.close()
                raise AssertionError(f"private backend/management port {port} is reachable from this client")


def run_harnesses(names, args, server, output, tokens, result):
    versions = json.loads((ROOT / "configs/common/harness-versions.json").read_text())
    packages = {"codex": "@openai/codex", "claude": "@anthropic-ai/claude-code", "opencode": "opencode-ai"}
    for name in names:
        row = harness_matrix(args.provider)[name]
        if row["status"] == "blocked":
            result["harnesses"][name] = row
            print(f"BLOCKED {args.provider}/{name}: {row['reason']}", flush=True)
            continue
        print("RUN external client: " + name, flush=True)
        directory = output / name
        directory.mkdir(mode=0o700)
        env = client_environment(output / (name + "-home"))
        version = run_captured([name, "--version"], env=env, cwd=directory, timeout=30)
        assert version.returncode == 0 and re.search(r"(?<![\d.])" + re.escape(versions[packages[name]]) + r"(?![\d.])",
                                                   version.stdout), f"install pinned {name} {versions[packages[name]]}"
        subprocess.run(["git", "init", "-q", str(directory)], env=env, check=True)
        command = [sys.executable, str(ROOT / "scripts/common/harness.py"), name, "--provider", args.provider,
            "--model", args.model, "--url", args.url, "--ca-file", str(args.ca_file.resolve()),
            "--token-file", str(args.token_file.resolve()), "--prompt", TASK]
        deadline = (3600 if server.get("inference") == "cpu" else 1800) if args.mode == "real" else 180
        started = time.monotonic()
        try:
            process = run_captured(command, env=env, cwd=directory, timeout=deadline)
            code, text = process.returncode, process.stdout + process.stderr
        except subprocess.TimeoutExpired as error:
            code, text = 124, (error.output or "") + (error.stderr or "")
        private_write(output / (name + ".log"), redact(text, tokens))
        result["harnesses"][name] = {"status": "failed", "exit_code": code, "version": version.stdout.strip(),
            "seconds": round(time.monotonic() - started, 2), "timeout_seconds": deadline,
            "mode": "isolated noninteractive client home"}
        assert code == 0, f"{name} failed; inspect its private log"
        assert (directory / "add.py").is_file() and (directory / "test_add.py").is_file(), f"{name}: missing generated files"
        assert ran_tests(name, text), f"{name}: no successful unittest tool event"
        if args.mode == "mock":
            assert MARKER in text, f"{name}: missing tool continuation"
        verify_project(directory, env)
        result["harnesses"][name]["status"] = "passed"
        print("PASS external client: " + name, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--ca-file", required=True, type=Path)
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--second-token-file", type=Path, help="optional second signed subject; authenticate it separately")
    parser.add_argument("--expired-token-file", type=Path, help="optional correctly signed, expired caller JWT")
    parser.add_argument("--server-evidence", required=True, type=Path)
    parser.add_argument("--provider", choices=("vllm", "openai", "anthropic"), default="vllm")
    parser.add_argument("--mode", choices=("mock", "real"), default="mock")
    parser.add_argument("--model", required=True)
    parser.add_argument("--harness", choices=("codex", "opencode", "claude"))
    parser.add_argument("--output", type=Path, help="new private evidence directory; must not exist")
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error("run on the separate client as an ordinary user")
    args.url = origin(args.url)
    server = json.loads(args.server_evidence.read_text())
    validate_server(server, args.url, args.mode, args.provider, args.model)
    token = args.token_file.read_text().strip()
    claims = verified_claims(token, server["jwt_public_key"])
    tokens = [token]
    extra = {}
    for kind, path in (("second", args.second_token_file), ("expired", args.expired_token_file)):
        if path:
            value = path.read_text().strip()
            other = verified_claims(value, server["jwt_public_key"], expired=kind == "expired")
            if kind == "second" and other["sub"] == claims["sub"]:
                parser.error("the second caller must have a distinct subject")
            tokens.append(value)
            extra[kind] = value
    names = (args.harness,) if args.harness else HARNESSES
    output = (args.output or ROOT / ".state" / ("external-client-" + str(time.time_ns()))).resolve()
    output.mkdir(mode=0o700, parents=True)
    result = {"status": "running", "url": args.url, "mode": args.mode, "provider": args.provider, "model": args.model,
              "backend": server.get("inference"), "server_evidence_sha256": hashlib.sha256(args.server_evidence.read_bytes()).hexdigest(),
              "launcher_sha256": hashlib.sha256((ROOT / "scripts/common/harness.py").read_bytes()).hexdigest(),
              "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "client": {"system": platform.system(), "machine_id_sha256": machine_id(), "uid": os.geteuid()},
              "scope": "gateway JWT authentication and native client tool task",
              "checks": {}, "harnesses": harness_matrix(args.provider), "not_run": []}
    remote = Remote(args.url, args.ca_file.resolve(), token, args.provider, args.model, args.mode == "real")
    try:
        remote.tls_and_ports(server["tls_leaf_sha256"])
        result["checks"]["verified-CA-and-private-ports"] = "passed"
        probe = "/v1/messages" if args.provider == "anthropic" else "/v1/responses"
        for label, caller in (("missing", ""), ("invalid", "invalid"), *([("expired", extra["expired"])] if "expired" in extra else [])):
            assert remote.request(probe, {"model": args.model}, token=caller)[0] == 401, f"{label} JWT accepted"
            result["checks"][label + "-JWT"] = "rejected"
        if "expired" not in extra:
            result["not_run"].append("signed-expired-JWT")
        if args.provider != "anthropic":
            status, payload = remote.request("/v1/models", method="GET")
            assert status == 200 and any(item["id"] == args.model for item in json.loads(payload)["data"]), \
                "gateway catalog does not contain the selected model"
            result["checks"]["gateway-model-list"] = "passed; interactive selector remains unqualified"
        if "second" in extra:
            status, _ = remote.request(probe, {"model": args.model, "input": "Reply ready.",
                "messages": [{"role": "user", "content": "Reply ready."}], "max_tokens": 2048}, token=extra["second"])
            assert status == 200, "second subject inference failed"
            result["checks"]["second-subject-inference"] = "passed; shared quota remains unqualified"
        paths = {"vllm": ("/v1/chat/completions", "/v1/responses", "/v1/messages"),
                 "openai": ("/v1/chat/completions", "/v1/responses"), "anthropic": ("/v1/messages",)}[args.provider]
        for path in paths:
            for stream in (False, True):
                body = {"model": args.model, "stream": stream}
                if path == "/v1/responses":
                    body.update(input="Reply with the word ready.", max_output_tokens=2048)
                else:
                    body.update(messages=[{"role": "user", "content": "Reply with the word ready."}], max_tokens=2048)
                    if stream and path == "/v1/chat/completions":
                        body["stream_options"] = {"include_usage": True}
                status, payload = remote.request(path, body)
                assert status == 200, f"{path}: HTTP {status}"
                if not stream:
                    assert json.loads(payload).get("model") == args.model, "API response names a different model"
                if args.mode == "real":
                    check_real_answer(path, payload, stream)
                else:
                    check(path, payload, stream, model=args.model)
                result["checks"][f"{path}:stream={stream}"] = "passed"
        run_harnesses(names, args, server, output, tokens, result)
        result["status"] = ("passed-automated-subset" if all(row["status"] == "passed" for row in result["harnesses"].values())
                            else "partial")
    except BaseException as error:
        result["status"] = "failed"
        result["error"] = redact(str(error), tokens)
        if isinstance(error, Exception):
            raise RuntimeError(result["error"]) from None
        raise
    finally:
        private_write(output / "result.json", json.dumps(result, indent=2) + "\n")
        print("Private external-client evidence: " + str(output), flush=True)


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("Run without Python -O")
    def interrupted(*_):
        raise InterruptedError("external-client qualification interrupted")
    signal.signal(signal.SIGTERM, interrupted)
    try:
        main()
    except (OSError, ValueError, RuntimeError, AssertionError, subprocess.SubprocessError) as error:
        raise SystemExit("External-client qualification failed: " + str(error)) from None
