#!/usr/bin/env python3
"""Run real harness entry points with fake CLI/SSH; never contact a gateway."""
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
import urllib.error
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[2]


class OpenCodeFixtureTest(unittest.TestCase):
    def test_streamed_write_command_and_final_continuation(self):
        fixture = runpy.run_path(str(Path(__file__).with_name('opencode-provider.py')))
        body = {'model': 'fixture-model', 'messages': [], 'tools': [
            {'type': 'function', 'function': {'name': name}} for name in ('write', 'bash')]}
        complete = fixture['completion']
        stream = fixture['provider'].events
        for expected, call_id in [('write', 'call_write'), ('bash', 'call_bash')]:
            result = complete('/v1/chat/completions', body)
            call = result['choices'][0]['message']['tool_calls'][0]
            self.assertEqual(call['function']['name'], expected)
            self.assertEqual(call['id'], call_id)
            frames = b''.join(stream('/v1/chat/completions', result))
            self.assertIn(b'[DONE]', frames)
            self.assertIn(expected.encode(), frames)
            body['messages'].append({'role': 'tool', 'tool_call_id': call_id, 'content': 'success'})
        result = complete('/v1/chat/completions', body)
        self.assertEqual(result['choices'][0]['finish_reason'], 'stop')
        self.assertEqual(result['choices'][0]['message']['content'], 'OPENCODE_TOOL_OK')
        self.assertNotIn('tool_calls', result['choices'][0]['message'])


class AuthenticationEvidenceTest(unittest.TestCase):
    def test_unrelated_failure_cannot_pass_authentication_check(self):
        native = runpy.run_path(str(Path(__file__).with_name('openclaw-native.py')))
        check = native['assert_authentication_rejection']
        fixture = native['fixture_module'].provider.Provider(ports=(0, 0, 0))
        fixture.start()
        self.addCleanup(fixture.close)
        with tempfile.TemporaryDirectory() as directory:
            proof = Path(directory) / 'proof.txt'
            failed = subprocess.CompletedProcess([], 125)
            with self.assertRaisesRegex(RuntimeError, 'No fresh upstream authentication rejection'):
                check(failed, proof, [])
            body = json.dumps({'model': 'fixture-model', 'messages': []}).encode()
            request = urllib.request.Request(
                f'http://127.0.0.1:{fixture.ports[0]}/v1/chat/completions', data=body,
                headers={'Content-Type': 'application/json', 'Authorization': 'Bearer wrong-synthetic-key'})
            with self.assertRaises(urllib.error.HTTPError) as rejected:
                urllib.request.urlopen(request, timeout=5)
            self.assertEqual(rejected.exception.code, 403)
            records = list(fixture.records)
            check(failed, proof, records)
            with self.assertRaisesRegex(RuntimeError, 'No fresh upstream authentication rejection'):
                check(failed, proof, [dict(record, credential_ok=True) for record in records])
            with self.assertRaisesRegex(RuntimeError, 'No fresh upstream authentication rejection'):
                check(failed, proof, [dict(record, classification_clean=False) for record in records])
            with self.assertRaisesRegex(RuntimeError, 'reported as success'):
                check(subprocess.CompletedProcess([], 0), proof, records)
            proof.write_text('unexpected success')
            with self.assertRaisesRegex(RuntimeError, 'reported as success'):
                check(failed, proof, records)


class HarnessTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.env = dict(os.environ, PATH=f"{self.work}:{os.environ['PATH']}",
                        OPENSHELL_BIN=str(self.work / "openshell"),
                        CAPTURE=str(self.work / "capture"), PRAXIS_PORT="18080",
                        PRAXIS_API_PREFIX="", OPENSHELL_SANDBOX_CPU="2", OPENSHELL_SANDBOX_MEMORY="4Gi",
                        OPENSHELL_MODEL_ID='fixture"quoted')
        for name, source in {
            "openshell": '''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]

if args[:3] == ["sandbox", "template", "list"]:
    state = pathlib.Path(os.environ["CAPTURE"] + ".templates")
    data = json.loads(state.read_text()) if state.exists() else {}
    print(json.dumps({"templates":list(data.values()), "next_page_token":""}))
    sys.exit()
if args[:3] == ["sandbox", "template", "create"]:
    state = pathlib.Path(os.environ["CAPTURE"] + ".templates")
    data = json.loads(state.read_text()) if state.exists() else {}
    name = args[3]
    record = {"name":name,"image":args[args.index("--image")+1],
              "resources":{"cpu":args[args.index("--cpu")+1],"memory":args[args.index("--memory")+1]},
              "environment":{},"labels":{}}
    for flag,key in [("--label","labels"),("--env","environment")]:
        for index,argument in enumerate(args):
            if argument == flag:
                k,v=args[index+1].split("=",1);record[key][k]=v
    data[name]=record;state.write_text(json.dumps(data));sys.exit()
if args[:3] == ["sandbox", "template", "get"]:
    print(json.dumps(json.loads(pathlib.Path(os.environ["CAPTURE"] + ".templates").read_text())[args[3]]))
    sys.exit()
if args[:2] == ["sandbox", "create"]:
    pathlib.Path(os.environ["CAPTURE"] + ".args").write_text(json.dumps(args))
    p = pathlib.Path(args[args.index("--policy") + 1])
    pathlib.Path(os.environ["CAPTURE"]).write_text(p.read_text())
if args[:1] == ["logs"]:
    print("Acknowledged initial policy revision as loaded")
if args[:2] == ["sandbox", "list"]:
    if "--output" in args and args[args.index("--output") + 1] == "json":
        print(json.dumps({"sandboxes": [{"name": "test", "phase": "Ready"}]}))
    else:
        print("test Ready")
''',
            "ssh": '#!/bin/sh\nprintf "%s\\n" "$@" > "$CAPTURE.ssh"\ncat > "$CAPTURE.provider"\n',
        }.items():
            script = self.work / name
            script.write_text(source)
            script.chmod(0o755)

    def create(self, harness, profile, integrated=False, success=True, config_dir=None, provider=None):
        # Each invocation must produce fresh evidence, including subtests.
        for name in ("capture", "capture.provider"):
            (self.work / name).unlink(missing_ok=True)
        args = ["bash", str(ROOT / f"openshell/harnesses/{harness}/create.sh"),
                "--profile", profile, "--name", "test"]
        if integrated:
            args += ["--config", str(ROOT / (config_dir or "configs/openshell-praxis"))]
        if provider:
            args += ["--provider", provider]
        result = subprocess.run(args, env=self.env, capture_output=True, text=True, timeout=10)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
            return yaml.safe_load((self.work / "capture").read_text())
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("readonly variable", result.stderr, "argument validation was never reached")
        self.assertNotIn("unbound variable", result.stderr)
        self.assertFalse((self.work / "capture").exists())
        return result.stderr

    def test_every_standalone_create_entry_point_and_profile(self):
        for harness in ("opencode", "codex", "openclaw"):
            for profile in ("review", "dev", "automation", "interactive"):
                with self.subTest(harness=harness, profile=profile):
                    policy = self.create(harness, profile)
                    source = ROOT / f"openshell/harnesses/{harness}/profiles/{profile}/policy.yaml"
                    self.assertEqual(policy, yaml.safe_load(source.read_text()))
                    for rule in policy["network_policies"].values():
                        for endpoint in rule["endpoints"]:
                            self.assertIs(type(endpoint["port"]), int)

    def test_integrated_policy_has_numeric_port_and_provider_json_escapes_model(self):
        for profile in ("review", "dev", "automation", "interactive"):
            policy = self.create("opencode", profile, integrated=True)
            endpoint = policy["network_policies"]["praxis_gateway"]["endpoints"][0]
            self.assertIs(type(endpoint["port"]), int)
            self.assertEqual(endpoint["port"], 18080)
            self.assertEqual({b["path"] for b in policy["network_policies"]["praxis_gateway"]["binaries"]},
                             {"/usr/bin/node-26", "/usr/local/bin/opencode"})
            config = json.loads((self.work / "capture.provider").read_text())
            model = self.env["OPENSHELL_MODEL_ID"]
            self.assertEqual(config["model"], f"praxis/{model}")
            provider = config["provider"]["praxis"]
            self.assertEqual(set(provider["models"]), {model})
            self.assertEqual(provider["options"]["baseURL"], "http://host.openshell.internal:18080/v1")

    def test_invalid_ports_fail_before_sandbox_creation(self):
        for port in ("0", "65536", "abc", "8080\nfoo: bar"):
            with self.subTest(port=port):
                self.env["PRAXIS_PORT"] = port
                error = self.create("opencode", "dev", integrated=True, success=False)
                self.assertIn("PRAXIS_PORT must be an integer", error)

    def test_qwen_route_prefix_is_rendered_without_changing_host_policy(self):
        self.env["PRAXIS_API_PREFIX"] = "/vllm"
        policy = self.create("opencode", "dev", integrated=True)
        config = json.loads((self.work / "capture.provider").read_text())
        self.assertEqual(config["provider"]["praxis"]["options"]["baseURL"],
                         "http://host.openshell.internal:18080/vllm/v1")
        self.assertEqual(config["provider"]["praxis"]["models"][self.env["OPENSHELL_MODEL_ID"]]["limit"],
                         {"context": 16384, "output": 4096})
        model = config["provider"]["praxis"]["models"][self.env["OPENSHELL_MODEL_ID"]]
        self.assertTrue(model["reasoning"])
        self.assertEqual(model["interleaved"], {"field": "reasoning"})
        endpoint = policy["network_policies"]["praxis_gateway"]["endpoints"][0]
        self.assertEqual(endpoint["host"], "host.openshell.internal")
        self.assertEqual(endpoint["port"], 18080)

    def test_resource_limits_reach_every_harness_create(self):
        for cpu, memory in (("2", "4Gi"), ("500m", "512Mi")):
            self.env.update(OPENSHELL_SANDBOX_CPU=cpu, OPENSHELL_SANDBOX_MEMORY=memory)
            for harness in ("opencode", "codex", "openclaw"):
                self.create(harness, "dev")
                args = json.loads((self.work / "capture.args").read_text())
                self.assertIn("--template", args)
                for flag in ("--from", "--cpu", "--memory", "--env", "--gpu"):
                    self.assertNotIn(flag,args)
                template=json.loads((self.work / "capture.templates").read_text())[args[args.index("--template")+1]]
                self.assertEqual(template["resources"],{"cpu":cpu,"memory":memory})
                self.assertIn("managed-by=secure-single-server",args)
                self.assertIn("--no-auto-providers", args)

    def test_arbitrary_api_prefix_is_rejected_before_creation(self):
        for prefix in ("/v1", "//example.org", "/vllm?secret=bad", "/../", "vllm"):
            self.env["PRAXIS_API_PREFIX"] = prefix
            self.assertIn("PRAXIS_API_PREFIX", self.create("opencode", "dev", integrated=True, success=False))

    def test_unsupported_integrated_harnesses_reject_config(self):
        for harness in ("codex",):
            for profile in ("review", "dev", "automation", "interactive"):
                with self.subTest(harness=harness, profile=profile):
                    error = self.create(harness, profile, integrated=True, success=False)
                    self.assertIn("--config", error)

    def test_openclaw_praxis_config_and_credential_isolation(self):
        for folder, prefix in (("configs/openshell-praxis/openclaw", ""),
                               ("configs/vllm/openclaw", ""),
                               ("configs/openshell-praxis/openclaw", "/vllm"),
                               ("configs/openshell-praxis/openclaw", "/providers/team")):
            with self.subTest(folder=folder, prefix=prefix):
                self.env["PRAXIS_API_PREFIX"] = prefix
                policy = self.create("openclaw", "dev", integrated=True, config_dir=folder)
                config = json.loads((self.work / "capture.provider").read_text())
                provider = config["models"]["providers"]["praxis"]
                self.assertEqual(provider["baseUrl"], f"http://host.openshell.internal:18080{prefix}/v1")
                self.assertEqual(provider["apiKey"], "local-placeholder")
                self.assertEqual(config["tools"]["allow"], ["read", "write"])
                self.assertEqual(provider["api"], "openai-completions")
                self.assertEqual(provider["models"][0]["id"], self.env["OPENSHELL_MODEL_ID"])
                self.assertEqual(config["agents"]["defaults"]["model"]["primary"],
                                 "praxis/" + self.env["OPENSHELL_MODEL_ID"])
                self.assertEqual(config["agents"]["defaults"]["workspace"], "/home/node/.openclaw/workspace")
                self.assertFalse(policy["filesystem_policy"]["include_workdir"])
                self.assertIn('/app', policy["filesystem_policy"]["read_only"])
                self.assertNotIn('/app', policy["filesystem_policy"]["read_write"])
                if folder == "configs/vllm/openclaw":
                    self.assertEqual(config["agents"]["defaults"]["models"]["praxis/" + self.env["OPENSHELL_MODEL_ID"]],
                                     {"params": {"chat_template_kwargs": {"enable_thinking": False}}})
                else:
                    self.assertNotIn("models", config["agents"]["defaults"])
                args = json.loads((self.work / "capture.args").read_text())
                self.assertIn("--no-auto-providers", args)
                self.assertNotIn("--provider", args)
                rule = policy["network_policies"]["praxis_gateway"]
                self.assertEqual(rule["endpoints"][0]["port"], 18080)
                self.assertEqual({b["path"] for b in rule["binaries"]},
                                 {"/usr/local/bin/node", "/usr/local/bin/openclaw"})
                hosts = {e["host"] for r in policy["network_policies"].values() for e in r["endpoints"]}
                self.assertNotIn("api.openai.com", hosts)
                self.assertNotIn("api.anthropic.com", hosts)
                if folder == "configs/vllm/openclaw":
                    self.assertEqual(hosts, {"host.openshell.internal"})

    def test_openclaw_invalid_configuration_fails_before_creation(self):
        folder = "configs/openshell-praxis/openclaw"
        for port in ("0", "65536", "not-a-port"):
            self.env["PRAXIS_PORT"] = port
            self.create("openclaw", "dev", integrated=True, success=False, config_dir=folder)
        self.env["PRAXIS_PORT"] = "8080"
        self.create("openclaw", "dev", integrated=True, success=False,
                    config_dir=folder, provider="direct-key")
        for profile in ("review", "automation", "interactive"):
            self.create("openclaw", profile, integrated=True, success=False, config_dir=folder)
        for model in ("", "model\nmalformed"):
            self.env["OPENSHELL_MODEL_ID"] = model
            self.create("openclaw", "dev", integrated=True, success=False, config_dir=folder)
        self.env["OPENSHELL_MODEL_ID"] = "test-model"
        for prefix in ("/elsewhere", "/providers/", "/providers/TEAM", "/providers/team/../openai", "/providers/a" + "b" * 32):
            self.env["PRAXIS_API_PREFIX"] = prefix
            self.create("openclaw", "dev", integrated=True, success=False, config_dir=folder)

    def test_integrated_policy_ports(self):
        for source in (ROOT / "configs/openshell-praxis/profiles").glob("*/policy.yaml"):
            with self.subTest(profile=source.parent.name):
                policy = yaml.safe_load(source.read_text().replace("@@PRAXIS_PORT@@", "18080"))
                port = policy["network_policies"]["praxis_gateway"]["endpoints"][0]["port"]
                self.assertIs(type(port), int, "OpenShell schema requires an unsigned integer")

    def test_bootc_local_backend_owns_model_and_port_from_catalog(self):
        for backend in ("vllm", "remote-vllm"):
            self.env["OPENSHELL_BOOTC_BACKEND"] = backend
            for harness in ("opencode", "openclaw"):
                self.create(harness, "dev")
                config = json.loads((self.work / "capture.provider").read_text())
                if harness == "opencode":
                    provider = config["provider"]["praxis"]
                    self.assertEqual(config["model"], "praxis/Qwen/Qwen3-8B")
                    self.assertEqual(provider["options"]["baseURL"], "http://host.openshell.internal:8080/v1")
                else:
                    self.assertEqual(config["agents"]["defaults"]["model"]["primary"], "praxis/Qwen/Qwen3-8B")
                    self.assertEqual(config["models"]["providers"]["praxis"]["baseUrl"], "http://host.openshell.internal:8080/v1")
                args = json.loads((self.work / "capture.args").read_text())
                self.assertIn("backend=" + backend, args)
                self.assertNotIn("--provider", args)
                for forbidden in ("--provider", "--config"):
                    self.create(harness, "dev", success=False,
                                provider="direct" if forbidden == "--provider" else None,
                                integrated=forbidden == "--config")

    def test_catalog_only_profile_reaches_existing_entry_point(self):
        catalog = self.work / "catalog"
        catalog.mkdir()
        data = json.loads((ROOT / "configs/templates/opencode.json").read_text())
        entry = next(item.copy() for item in data["templates"] if item["backend"] == "standalone")
        entry.update(profile="tiny", cpu="500m", memory="512Mi")
        (catalog / "opencode.json").write_text(json.dumps({"version":1,"templates":[entry]}))
        self.env["OPENSHELL_TEMPLATE_DIR"] = str(catalog)
        self.env.pop("OPENSHELL_SANDBOX_CPU")
        self.env.pop("OPENSHELL_SANDBOX_MEMORY")
        self.create("opencode", "tiny")
        args = json.loads((self.work / "capture.args").read_text())
        template = json.loads((self.work / "capture.templates").read_text())[args[args.index("--template")+1]]
        self.assertEqual(template["resources"], {"cpu":"500m","memory":"512Mi"})
        self.assertIn("profile=tiny", args)

    def test_all_connect_entry_points_propagate_ssh_failure(self):
        # A missing executable or failed SSH session must not look successful.
        (self.work / "ssh").write_text('#!/bin/sh\nprintf called > "$CAPTURE.ssh"\nexit 255\n')
        for harness in ("opencode", "codex", "openclaw"):
            with self.subTest(harness=harness):
                marker = self.work / "capture.ssh"
                marker.unlink(missing_ok=True)
                result = subprocess.run(["bash", str(ROOT / f"openshell/harnesses/{harness}/connect.sh"),
                    "--name", "test"], env=self.env, capture_output=True, text=True, timeout=10)
                self.assertTrue(marker.exists(), "connect failed before invoking SSH")
                self.assertEqual(result.returncode, 255, result.stderr)

    def test_openclaw_waits_for_initial_policy_before_uploading_config(self):
        cli = self.work / "openshell"
        source = cli.read_text().replace('print("Acknowledged initial policy revision as loaded")',
            'marker = pathlib.Path(os.environ["CAPTURE"] + ".polls")\n'
            '    count = int(marker.read_text()) + 1 if marker.exists() else 1\n'
            '    marker.write_text(str(count))\n'
            '    if count >= 2: print("Acknowledged initial policy revision as loaded")')
        cli.write_text(source)
        self.create("openclaw", "dev", integrated=True, config_dir="configs/vllm/openclaw")
        self.assertEqual((self.work / "capture.polls").read_text(), "2")
        self.assertTrue((self.work / "capture.provider").exists())
        cli.write_text(source.replace('if count >= 2: print("Acknowledged initial policy revision as loaded")', 'sys.exit(42)'))
        (self.work / "capture.provider").unlink()
        result = subprocess.run(["bash", str(ROOT / "openshell/harnesses/openclaw/create.sh"),
                                 "--profile", "dev", "--name", "test", "--config", str(ROOT / "configs/vllm/openclaw")],
                                env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 42)
        self.assertFalse((self.work / "capture.provider").exists())

    def test_openclaw_run_transmits_prompt_over_stdin_and_propagates_failure(self):
        prompt = "Write a file; $(touch should-not-exist)\nThen read it."
        result = subprocess.run(["bash", str(ROOT / "openshell/harnesses/openclaw/run.sh"),
                                 "--name", "test", "--message", prompt], env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.work / "capture.provider").read_text(), prompt + "\n")
        self.assertIn("SQLITE_TMPDIR=/tmp", (self.work / "capture.ssh").read_text())
        self.assertFalse((ROOT / "should-not-exist").exists())
        (self.work / "ssh").write_text('#!/bin/sh\ncat >/dev/null\nexit 42\n')
        result = subprocess.run(["bash", str(ROOT / "openshell/harnesses/openclaw/run.sh"),
                                 "--name", "test", "--message", "hello"], env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 42)

    def test_invalid_create_arguments_fail_with_an_argument_error(self):
        for harness in ("opencode", "codex", "openclaw"):
            for args in (["--profile"], ["--profile", "missing"], ["--unknown"]):
                with self.subTest(harness=harness, args=args):
                    result = subprocess.run(["bash", str(ROOT / f"openshell/harnesses/{harness}/create.sh"),
                        *args], env=self.env, capture_output=True, text=True, timeout=10)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn("readonly variable", result.stderr)
                    self.assertNotIn("unbound variable", result.stderr)
                    self.assertFalse((self.work / "capture").exists())


if __name__ == "__main__":
    unittest.main()
