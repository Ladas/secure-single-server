#!/usr/bin/env python3
"""Exercise the pinned image with native TLS/JWT and synthetic local providers.

No real provider keys or outbound inference. Only a random loopback host port
is published. The test removes only its own uniquely named container.
"""

import base64
import http.client
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[2]
ENGINE = os.environ.get("CONTAINER_ENGINE", "podman")
IMAGE = os.environ.get("PRAXIS_IMAGE", "quay.io/opendatahub/praxis-experimental@sha256:"
                       "a3006352106c2264427faa79b57cf7b49287f3f9bfffe9b2eef869d3429988e8")
TOOL = ROOT / "scripts/remote-gateway/credentials"
VALKEY_IMAGE = "docker.io/valkey/valkey@sha256:63346cb24a61221e76bdf41acce99b3968a9fa83d8122144deab45394b27b4f2"


def run(*args):
    return subprocess.run(list(map(str, args)), check=True, capture_output=True).stdout.decode().strip()


def yaml_file(path):
    return json.loads(run("ruby", "-ryaml", "-rjson", "-e", "puts YAML.load_file(ARGV[0]).to_json", path))


def restart_gateway(name):
    # Docker may assign a different random host port after a restart.
    run(ENGINE, "restart", name)
    return run(ENGINE, "port", name, "8443/tcp").rsplit(":", 1)[1]


def wait_for_gateway(request, attempts=30):
    last_result = "no response"
    for attempt in range(attempts):
        try:
            status = request("/v1/models", method="GET")
            if status == 401:
                return
            last_result = f"HTTP {status}"
        except (OSError, urllib.error.URLError) as error:
            if isinstance(getattr(error, "reason", error), ssl.SSLCertVerificationError):
                raise
            last_result = str(error)
        if attempt + 1 < attempts:
            time.sleep(1)
    raise AssertionError(f"TLS/JWT endpoint did not become ready: {last_result}")


def expect_certificate_rejection(opener, url):
    try:
        with opener.open(url, timeout=5):
            pass
    except urllib.error.URLError as error:
        if isinstance(error.reason, ssl.SSLCertVerificationError):
            return
        raise AssertionError("expected a TLS certificate-verification failure, not HTTP or transport failure") from error
    raise AssertionError("invalid TLS certificate accepted")


def token(key, **overrides):
    claims = {"iss": "https://secure-single-server.local", "aud": "praxis-gateway", "sub": "test-user",
              "exp": int(time.time()) + 600}
    claims.update(overrides)
    enc = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=")
    message = enc(b'{"alg":"RS256","typ":"JWT"}') + b"." + enc(json.dumps(claims).encode())
    signature = subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(key)], input=message,
                               capture_output=True, check=True).stdout
    return (message + b"." + enc(signature)).decode()


def main():
    name = "praxis-remote-test-" + uuid.uuid4().hex[:12]
    profile = "valkey" if sys.argv[1:] == ["--valkey"] else "memory"
    if sys.argv[1:] not in ([], ["--valkey"]):
        raise ValueError("usage: image.py [--valkey]")
    # Architecture is the engine server's architecture, not the Mac client.
    run("bash", "-c", 'source "$1"; check_native_image "$2" "$3"', "native",
        ROOT / "scripts/common/lib.sh", ENGINE, IMAGE)
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        run(TOOL, "init-jwt", "--directory", work / "issuer")
        run(TOOL, "lab-tls", "--directory", work / "tls", "--hostname", "localhost")
        rendered = work / "rendered.yaml"
        run("bash", "-c", 'source "$1"; render_remote_config "$2" "$3" "$4"', "render",
            ROOT / "scripts/common/lib.sh", profile, ROOT / "configs/remote-gateway/gateway.yaml", rendered)
        config = yaml_file(rendered)
        files = {"tls.pem": work / "tls/server.pem", "tls-key.pem": work / "tls/server-key.pem",
                 "jwt-public.pem": work / "issuer/public.pem",
                 "policy.yaml": ROOT / "configs/remote-gateway/policy.yaml"}
        filters = config["filter_chains"][0]["filters"]
        for item in filters:
            if item["filter"] == "token_rate_limit":
                item["rules"][0]["capacity"] = 20
                item["rules"][0]["reserved_tokens"] = 10
        # Substitute only the network destinations; production authentication,
        # API selection, quota filters and credential injection remain intact.
        for index, cluster in enumerate(filters[-1]["clusters"]):
            cluster["endpoints"] = [f"127.0.0.1:{18080 + index}"]
            cluster.pop("tls")
            cluster.pop("http")
            provider = cluster["name"]
            expected = {"Authorization": "Bearer synthetic-openai"} if index == 0 else {
                "x-api-key": "synthetic-anthropic"}
            response = {"model": "test", "usage": {"prompt_tokens": 2, "completion_tokens": 3,
                                                      "input_tokens": 2, "output_tokens": 3}}
            config["listeners"].append({"name": provider, "address": f"127.0.0.1:{18080 + index}",
                                         "filter_chains": [provider]})
            config["filter_chains"].append({"name": provider, "filters": [
                {"filter": "static_response", "status": 403, "body": "spoofed header forwarded",
                 "conditions": [{"when": {"headers": {"X-Model": "spoofed-model"}}}]},
                {"filter": "static_response", "status": 403, "body": "credential mismatch",
                 "conditions": [{"unless": {"headers": expected}}]},
                {"filter": "static_response", "status": 200, "body": json.dumps(response),
                 "headers": [{"name": "Content-Type", "value": "application/json"}]}]})
        config["insecure_options"] = {"allow_private_endpoints": True}
        target = work / "gateway.json"
        target.write_text(json.dumps(config))
        files["shared-gateway.yaml"] = target
        # Synthetic TLS key only. Individual read-only mounts also work with
        # Docker's UID 1001; the real installer uses root:service-group 0640.
        arguments = [ENGINE, "run", "--detach", "--name", name, "--read-only", "--cap-drop", "all",
                     "--security-opt", "no-new-privileges", "--user", "1001:1001",
                     "-p", "127.0.0.1::8443", "-e", "OPENAI_API_KEY=synthetic-openai",
                     "-e", "ANTHROPIC_API_KEY=synthetic-anthropic"]
        if Path(ENGINE).name == "podman":
            arguments += ["--userns", "keep-id:uid=1001,gid=1001"]
        for destination, source in files.items():
            if source.is_relative_to(work):
                source.chmod(0o644)
            arguments += ["--mount", f"type=bind,source={source},target=/etc/praxis/{destination},readonly"]
        try:
            if profile == "valkey":
                run("bash", "-c", 'source "$1"; check_native_image "$2" "$3"', "native",
                    ROOT / "scripts/common/lib.sh", ENGINE, VALKEY_IMAGE)
                run(ENGINE, "network", "create", name)
                run(ENGINE, "volume", "create", name)
                acl = work / "users.acl"
                acl.write_text((ROOT / "configs/common/valkey/users.acl.example").read_text().replace(
                    "SHA256_PASSWORD", "69d6dc9618d24d693cad07557702696090d0f575d9c0868384b8001fd1252358"))
                acl.chmod(0o644)
                vk_args = [ENGINE, "run", "--detach", "--name", name + "-valkey", "--network", name,
                    "--network-alias", "praxis-valkey", "--user", "999:999", "--read-only", "--cap-drop", "all",
                    "--security-opt", "no-new-privileges", "-v", name + ":/data",
                    "--mount", f"type=bind,source={acl},target=/run/secrets/users.acl,readonly",
                    "--mount", f"type=bind,source={ROOT}/configs/common/valkey/valkey.conf,target=/etc/valkey.conf,readonly"]
                if Path(ENGINE).name == "podman":
                    vk_args += ["--userns", "keep-id:uid=999,gid=999"]
                run(*vk_args, VALKEY_IMAGE, "valkey-server", "/etc/valkey.conf")
                arguments += ["--network", name, "-e",
                    "TOKEN_RATE_LIMIT_VALKEY_URL=redis://praxis:local-valkey-test@praxis-valkey:6379/0"]
            run(*arguments, IMAGE, "-c", "/etc/praxis/shared-gateway.yaml")
            port = run(ENGINE, "port", name, "8443/tcp").rsplit(":", 1)[1]
            context = ssl.create_default_context(cafile=str(work / "tls/ca.pem"))
            # Never inherit HTTP proxy settings for the loopback-only fixture.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                 urllib.request.HTTPSHandler(context=context))
            def request(path, bearer=None, method="POST"):
                headers = {"Content-Type": "application/json", "X-Model": "spoofed-model",
                           "X-Api-Key": "spoofed-provider-key"}
                if bearer is not None:
                    headers["Authorization"] = "Bearer " + bearer
                req = urllib.request.Request(f"https://localhost:{port}{path}",
                    data=b'{"model":"test","messages":[],"max_tokens":4}' if method == "POST" else None,
                    headers=headers, method=method)
                try:
                    with opener.open(req, timeout=5) as response:
                        return response.status
                except urllib.error.HTTPError as error:
                    return error.code
            wait_for_gateway(request)
            key = work / "issuer/private.pem"
            for bad in [None, "invalid", token(key, exp=int(time.time()) - 600),
                        token(key, iss="https://wrong.local"), token(key, aud="wrong")]:
                assert request("/v1/messages", bad) == 401, "invalid caller accepted"
            valid = token(key)
            assert request("/v1/messages", valid[:-10] + "invalidsig") == 401, "bad signature accepted"
            assert request("/not-an-api", valid) == 404, "unknown route accepted"
            for path, method in [("/v1/messages/batches", "POST"), ("/v1/messages/batches", "GET"),
                                 ("/v1/messages/batches/batch-test/results", "GET"),
                                 ("/v1/messages/batches/batch-test/cancel", "POST")]:
                assert request(path, valid, method) == 404, "unsupported batch API reached provider"
            assert request("/v1/messages/count_tokens", valid) == 200, "native token-count endpoint was blocked"
            time.sleep(0.55)
            for path in ["/v1/responses", "/v1/chat/completions", "/v1/messages"]:
                assert request(path, valid) == 200, f"native API/credential injection failed: {path}"
                time.sleep(0.55)  # avoid confusing request throttling with quota exhaustion
            assert request("/v1/responses", valid) == 200, "remaining OpenAI quota not usable"
            time.sleep(0.55)
            assert request("/v1/responses", valid) == 429, "exhausted OpenAI quota not enforced"
            time.sleep(0.55)
            assert request("/v1/messages", valid) == 200, "OpenAI exhaustion consumed the Anthropic quota"
            if profile == "memory":
                time.sleep(0.55)
                assert request("/v1/messages", valid) == 200, "remaining Anthropic quota not usable"
                time.sleep(0.55)
                assert request("/v1/messages", valid) == 429, "exhausted Anthropic quota not enforced"
                assert request("/v1/messages/batches", valid) == 404, "batch bypass after quota exhaustion"
            if profile == "valkey":
                time.sleep(2)  # allow the documented AOF everysec flush
                port = restart_gateway(name)
                run(ENGINE, "restart", name + "-valkey")
                wait_for_gateway(request, attempts=20)
                time.sleep(1)
                assert request("/v1/responses", valid) == 429, "restart reset persistent OpenAI quota"
                run(ENGINE, "stop", "--time", "1", name + "-valkey")
                # Anthropic still has capacity. An outage must not bypass admission.
                assert request("/v1/messages", valid) >= 400, "Valkey outage allowed inference"
                assert request("/v1/messages/batches", valid) == 404, "batch bypass during Valkey outage"
            # A private CA is not trusted by default. No insecure TLS fallback.
            untrusted = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            expect_certificate_rejection(untrusted, f"https://localhost:{port}/v1/models")
            expect_certificate_rejection(opener, f"https://127.0.0.1:{port}/v1/models")
            try:
                with untrusted.open(f"http://localhost:{port}/v1/models", timeout=5) as response:
                    assert response.status >= 400, "plaintext inference accepted"
            except (urllib.error.URLError, http.client.HTTPException, ConnectionResetError):
                pass
            print(f"PASS ({profile}): TLS trust/hostname, JWT denials, native APIs, credentials and independent token quotas")
        except Exception:
            print(run(ENGINE, "logs", "--tail", "12", name))  # synthetic keys only
            raise
        finally:
            subprocess.run([ENGINE, "rm", "--force", name], capture_output=True, check=False)
            if profile == "valkey":
                for command in [["rm", "--force", name + "-valkey"], ["network", "rm", name], ["volume", "rm", name]]:
                    subprocess.run([ENGINE, *command], capture_output=True, check=False)


if __name__ == "__main__":
    main()
