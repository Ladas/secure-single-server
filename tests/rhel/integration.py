#!/usr/bin/env python3
"""Qualify the installed RHEL gateway using private fixtures and real coding CLIs."""
import argparse
import json
import os
from pathlib import Path
import pwd
import shutil
import signal
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

from host import ROOT, STATE, capture, run, service, service_output
sys.path.insert(0, str(ROOT / "tests/common"))
from contracts import check
sys.path.insert(0, str(ROOT / "scripts/common"))
from harness import configuration

USER = "praxis-smoke"
MARKER = "PRAXIS_SMOKE_TOOL_OK"
TASK = '''Create these two files in the current project, then run their tests.
Use the file read/write tools or Python 3 to create the files. The shell tool
permits only python3 commands; do not use touch, cat, mkdir or other shell commands.

add.py:
def add(a, b):
    return a + b

test_add.py:
import unittest
from add import add

class TestAdd(unittest.TestCase):
    def test_values(self):
        self.assertEqual(add(2, 3), 5)
        self.assertEqual(add(-2, -3), -5)
        self.assertEqual(add(0, 0), 0)

Run python3 -m unittest -v using the shell tool. If it fails, read the files,
fix them and rerun the tests. Report completion only after a successful test
run. Do not install packages, access credentials or modify other projects.
'''


def ran_tests(name, output):
    """Require a successful native tool event, not a model's claim of success."""
    claude_calls = set()
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if name == "codex" and event.get("type") == "item.completed":
            item = event.get("item", {})
            if item.get("type") == "command_execution" and item.get("exit_code") == 0 and "unittest" in item.get("command", ""):
                return True
        if name == "opencode" and event.get("type") == "tool_use":
            part = event.get("part", {})
            state = part.get("state", {})
            if (part.get("tool") == "bash" and state.get("status") == "completed"
                    and state.get("metadata", {}).get("exit") == 0
                    and "unittest" in state.get("input", {}).get("command", "")):
                return True
        if name == "claude" and isinstance(event.get("message"), dict):
            for item in event.get("message", {}).get("content", []):
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "tool_use" and item.get("name") == "Bash" and "unittest" in item.get("input", {}).get("command", ""):
                    claude_calls.add(item["id"])
                if item.get("type") == "tool_result" and item.get("tool_use_id") in claude_calls and not item.get("is_error"):
                    return True
    return False


class InstalledGateway:
    def __init__(self, args):
        self.args = args
        self.last_request = 0
        self.token = "local-placeholder"
        self.base = "http://127.0.0.1:8080"
        self.provider = getattr(args, "provider", "cloud")
        self.real = getattr(args, "real", False)
        self.prefix = "/vllm" if self.provider == "vllm" else ""
        self.model = "qwen3-8b" if self.provider == "vllm" else "fixture"
        handlers = [urllib.request.ProxyHandler({})]
        if args.scenario == "remote-gateway":
            # Public HTTPS is checked from the workstation by run.py. AWS SGs
            # intentionally do not allow a VM's public-IP hairpin connection.
            self.base = "https://127.0.0.1:8443"
            self.token = (ROOT / "material/caller.jwt").read_text().strip()
            handlers.append(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(ROOT / "material/ca.pem"))))
        self.opener = urllib.request.build_opener(*handlers)
        self.base += self.prefix

    def control(self, mode=None, reset=False):
        if self.real:
            return {"records": []}
        port = "19001" if self.provider == "vllm" else "19000"
        code = ('import json,urllib.request; r=urllib.request.Request("http://127.0.0.1:' + port + '/'
                + ("state" if mode is None else "scenario") + '",data='
                + ("None" if mode is None else repr(json.dumps({"mode": mode, "reset": reset}).encode()))
                + ',headers={"Content-Type":"application/json"}); print(urllib.request.urlopen(r).read().decode())')
        return json.loads(service_output("podman", "exec", "praxis-rhel-mock", "python3", "-c", code))

    def request(self, path, body=None, token=None, method="POST"):
        time.sleep(max(0, 0.65 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        base = self.base
        if self.args.scenario == "all-in-one" and path.startswith("/v1/messages"):
            base = "http://127.0.0.1:8081" + self.prefix
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + (self.token if token is None else token),
                   "X-Model": "spoofed-model", "X-Api-Key": "spoofed-key"}
        req = urllib.request.Request(base + path, data=json.dumps(body or {"model": self.model, "messages": [],
                                       "max_tokens": 4}).encode() if method == "POST" else None,
                                     headers=headers, method=method)
        try:
            response = self.opener.open(req, timeout=600 if self.real else 15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.read().decode()

    def contracts(self):
        self.control("ok", reset=True)
        if self.args.scenario == "remote-gateway":
            for token in ("", "invalid"):
                status, _ = self.request("/v1/responses", token=token)
                assert status == 401, "missing or invalid caller JWT accepted"
            assert not self.control()["records"], "rejected caller reached provider"
        for path in ("/v1/responses", "/v1/chat/completions", "/v1/messages"):
            for stream in (False, True):
                status, body = self.request(path, {"model": self.model, "input": "hello", "messages": [],
                                                  "max_tokens": 4, "stream": stream})
                assert status == 200, f"{path} failed with HTTP {status}: {body[:200]}"
                check(path, body, stream, model=self.model)
        records = self.control()["records"]
        assert len(records) == 6 and all(r["credential_ok"] and r["classification_clean"] for r in records), records
        print("PASS: installed gateway native Responses/Chat/Messages JSON+SSE and provider credential replacement", flush=True)

    def real_contracts(self):
        status, body = self.request("/v1/models", method="GET")
        assert status == 200 and any(model["id"] == self.model for model in json.loads(body)["data"]), body[:300]
        if self.args.scenario == "remote-gateway":
            assert self.request("/v1/models", method="GET", token="invalid")[0] == 401
        for path in ("/v1/chat/completions", "/v1/responses", "/v1/messages"):
            for stream in (False, True):
                print(f"RUN: real Qwen {path}, stream={stream}", flush=True)
                request = {"model": self.model, "stream": stream}
                if path == "/v1/responses":
                    request.update(input="Reply with the word ready.", max_output_tokens=32)
                else:
                    request.update(messages=[{"role": "user", "content": "Reply with the word ready."}], max_tokens=32)
                    if stream and path == "/v1/chat/completions":
                        request["stream_options"] = {"include_usage": True}
                status, body = self.request(path, request)
                assert status == 200, f"real {path}: HTTP {status}: {body[:500]}"
                assert "usage" in body and "ready" in body.lower(), f"real {path} missing text/usage: {body[:500]}"
                if stream:
                    end = {"/v1/responses": "response.completed", "/v1/messages": "message_stop",
                           "/v1/chat/completions": "[DONE]"}[path]
                    assert end in body, f"incomplete real {path} stream"
                print(f"PASS: real Qwen {path}, stream={stream}, final usage received", flush=True)
        status, _ = self.request("/v1/chat/completions", {"model": "unknown-local-model", "messages": []})
        assert status == 404, "unknown local model did not fail closed"


def run_captured(command, *, timeout, **kwargs):
    """Bound the entire harness process group and retain evidence on timeout."""
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, start_new_session=True, **kwargs) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                stdout, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate()
            raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr) from None
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def user_command(*command, directory=None, environment=None, timeout=300):
    account = pwd.getpwnam(USER)
    env = {"HOME": account.pw_dir, "USER": USER, "LOGNAME": USER,
           "PATH": account.pw_dir + "/.local/bin:/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}
    env.update(environment or {})
    # Resolve the administrator utility before applying the ordinary user's PATH.
    runuser = shutil.which("runuser") or "/usr/sbin/runuser"
    return run_captured([runuser, "-u", USER, "--preserve-environment", "--", *map(str, command)],
                        cwd=directory or account.pw_dir, env=env, timeout=timeout)


def setup_harnesses():
    run("install", "-m", "0755", ROOT / "scripts/common/harness.py", "/usr/local/bin/praxis-harness")
    owner_marker = STATE / "harness-user"
    try:
        account = pwd.getpwnam(USER)
        if not owner_marker.is_file():
            raise ValueError("refusing to adopt an existing unrelated harness account")
    except KeyError:
        run("useradd", "--create-home", "--shell", "/bin/bash", USER)
        owner_marker.write_text(USER + "\n")
        account = pwd.getpwnam(USER)
    assert USER not in capture("getent", "group", "wheel").split(":")[-1].split(",")
    run("dnf", "module", "switch-to", "-y", "nodejs:22")
    run("dnf", "install", "-y", "nodejs", "npm")
    versions_file = STATE / "harness-versions.json"
    versions = json.loads((ROOT / "tests/rhel/harness-versions.json").read_text())
    versions_file.write_text(json.dumps(versions, indent=2) + "\n")
    print("Harness versions: " + json.dumps(versions), flush=True)
    result = user_command("npm", "install", "--prefix", account.pw_dir + "/.local", "--global",
                          *[f"{name}@{version}" for name, version in versions.items()], timeout=600)
    if result.returncode:
        raise RuntimeError("harness installation failed: " + result.stderr[-2000:])
    for command in ("codex", "opencode", "claude"):
        result = user_command(command, "--version")
        assert result.returncode == 0, result.stderr
        print(result.stdout.strip(), flush=True)
    for path in ("/etc/praxis/shared-gateway.yaml", "/var/lib/praxis-svc"):
        result = user_command("test", "-r", path)
        assert result.returncode != 0, f"ordinary user can read {path}"
    assert account.pw_gid != pwd.getpwnam("praxis-svc").pw_gid


def harnesses(gateway, install=True, selected=None):
    if install:
        setup_harnesses()
    account = pwd.getpwnam(USER)
    root = Path(account.pw_dir) / "rhel-smoke"
    root.mkdir(mode=0o700, exist_ok=True)
    os.chown(root, account.pw_uid, account.pw_gid)
    ca = root / "ca.pem"
    if gateway.args.scenario == "remote-gateway":
        shutil.copyfile(ROOT / "material/ca.pem", ca)
        os.chown(ca, account.pw_uid, account.pw_gid)
        ca.chmod(0o600)
    for name in ("codex", "opencode", "claude"):
        if selected and name != selected:
            continue
        print(f"RUN: {name} with {'real' if gateway.real else 'mock'} {gateway.provider}", flush=True)
        directory = root / (gateway.provider + "-" + name + "-" + str(time.time_ns()))
        directory.mkdir(mode=0o700)
        os.chown(directory, account.pw_uid, account.pw_gid)
        result = user_command("git", "init", "-q", directory)
        assert result.returncode == 0, result.stderr
        provider = gateway.provider
        if provider == "cloud":
            provider = "anthropic" if name == "claude" else "openai"
        base = gateway.base.removesuffix(gateway.prefix) if gateway.prefix else gateway.base
        messages_base = base if gateway.args.scenario == "remote-gateway" else "http://127.0.0.1:8081"
        command, environment = configuration(name, provider, gateway.model, base, gateway.token,
                                             prompt=TASK, messages_base=messages_base)
        if gateway.args.scenario == "remote-gateway":
            environment.update(NODE_EXTRA_CA_CERTS=str(ca), SSL_CERT_FILE=str(ca))
        gateway.control("ok", reset=True)
        timed_out = False
        try:
            result = user_command(*command, directory=directory, environment=environment, timeout=1800 if gateway.real else 180)
        except subprocess.TimeoutExpired as error:
            timed_out = True
            result = subprocess.CompletedProcess(command, 124, error.output or "", error.stderr or "")
        # Credentials in output are replaced before writing test evidence.
        output = (result.stdout + result.stderr).replace(gateway.token, "[caller]")
        tag = f"{'real' if gateway.real else 'mock'}-{gateway.provider}-{name}-{gateway.args.profile}"
        (STATE / (tag + ".log")).write_text(output)
        assert not timed_out, f"{name} exceeded its time limit; partial evidence: {tag}.log"
        records = gateway.control()["records"]
        if not gateway.real:
            (STATE / (tag + "-provider.json")).write_text(json.dumps(records, indent=2))
        assert result.returncode == 0, f"{name} failed ({result.returncode}): {output[-3000:]}"
        assert (directory / "add.py").is_file() and (directory / "test_add.py").is_file(), f"{name} did not create the test project: {output[-3000:]}"
        checked = user_command("python3", "-m", "unittest", "-v", directory=directory)
        assert checked.returncode == 0, checked.stderr
        assert "Ran 0 tests" not in checked.stderr, "empty test suite does not qualify a harness"
        checked = user_command("python3", "-c", "from add import add; assert add(2,3)==5; assert add(-2,-3)==-5; assert add(0,0)==0", directory=directory)
        assert checked.returncode == 0, "generated add function failed independent checks"
        if gateway.real:
            assert ran_tests(name, output), f"{name} did not execute a successful unittest tool command"
        if not gateway.real:
            assert MARKER in output, f"{name} did not complete the tool continuation"
            assert records and all(r["credential_ok"] for r in records), "provider credential replacement failed"
            assert any(r["stream"] for r in records) and any(r["continuation"] for r in records), "missing stream/tool-result request"
        print(f"PASS: {name}: installed Praxis → {'real' if gateway.real else 'mock'} {gateway.provider} → files → unittest", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--hostname", required=True)
    parser.add_argument("--provider", choices=("cloud", "vllm"), default="cloud")
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--harness", choices=("codex", "opencode", "claude"))
    args = parser.parse_args()
    if not __debug__:
        raise SystemExit("Do not run qualification with Python -O")
    gateway = InstalledGateway(args)
    if args.real:
        if args.provider != "vllm":
            parser.error("automated real tests require vLLM; cloud calls are manual")
        results = {"scenario": args.scenario, "profile": args.profile, "model": gateway.model, "checks": {}}
        try:
            gateway.real_contracts()
            results["checks"]["protocols"] = "passed"
            setup_harnesses()
            for name in ([args.harness] if args.harness else ["codex", "opencode", "claude"]):
                try:
                    harnesses(gateway, install=False, selected=name)
                    results["checks"][name] = "passed"
                except (AssertionError, subprocess.TimeoutExpired) as error:
                    results["checks"][name] = "failed: " + str(error)
                    print(f"FAIL: real Qwen {name}: {error}", flush=True)
        finally:
            (STATE / f"real-vllm-{args.profile}-{time.time_ns()}.json").write_text(json.dumps(results, indent=2) + "\n")
        if any(value != "passed" for value in results["checks"].values()):
            raise SystemExit(1)
        return
    (STATE / f"baseline-{args.profile}.json").unlink(missing_ok=True)
    gateway.contracts()
    harnesses(gateway)
    (STATE / f"baseline-{args.profile}.json").write_text(json.dumps({
        "scenario": args.scenario, "profile": args.profile, "completed": time.time(),
        "checks": ["protocols", "credentials", "codex", "opencode", "claude"]}) + "\n")


if __name__ == "__main__":
    main()
