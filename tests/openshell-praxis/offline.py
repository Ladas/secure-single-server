#!/usr/bin/env python3
"""Run real harness entry points with fake CLI/SSH; never contact a gateway."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]


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
if args[:2] == ["sandbox", "create"]:
    pathlib.Path(os.environ["CAPTURE"] + ".args").write_text(json.dumps(args))
    p = pathlib.Path(args[args.index("--policy") + 1])
    pathlib.Path(os.environ["CAPTURE"]).write_text(p.read_text())
if args[:2] == ["sandbox", "list"]:
    if "--output" in args and args[args.index("--output") + 1] == "json":
        print(json.dumps({"sandboxes": [{"name": "test", "phase": "Ready"}]}))
    else:
        print("test Ready")
''',
            "ssh": '#!/bin/sh\ncat > "$CAPTURE.provider"\n',
        }.items():
            script = self.work / name
            script.write_text(source)
            script.chmod(0o755)

    def create(self, harness, profile, integrated=False, success=True):
        # Each invocation must produce fresh evidence, including subtests.
        for name in ("capture", "capture.provider"):
            (self.work / name).unlink(missing_ok=True)
        args = ["bash", str(ROOT / f"openshell/harnesses/{harness}/create.sh"),
                "--profile", profile, "--name", "test"]
        if integrated:
            args += ["--config", str(ROOT / "configs/openshell-praxis")]
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
                self.assertEqual(args[args.index("--cpu") + 1], cpu)
                self.assertEqual(args[args.index("--memory") + 1], memory)
                self.assertIn("--no-auto-providers", args)

    def test_arbitrary_api_prefix_is_rejected_before_creation(self):
        for prefix in ("/v1", "//example.org", "/vllm?secret=bad", "/../", "vllm"):
            self.env["PRAXIS_API_PREFIX"] = prefix
            self.assertIn("PRAXIS_API_PREFIX", self.create("opencode", "dev", integrated=True, success=False))

    def test_unsupported_integrated_harnesses_reject_config(self):
        for harness in ("codex", "openclaw"):
            for profile in ("review", "dev", "automation", "interactive"):
                with self.subTest(harness=harness, profile=profile):
                    error = self.create(harness, profile, integrated=True, success=False)
                    self.assertIn("--config", error)

    def test_integrated_policy_ports(self):
        for source in (ROOT / "configs/openshell-praxis/profiles").glob("*/policy.yaml"):
            with self.subTest(profile=source.parent.name):
                policy = yaml.safe_load(source.read_text().replace("@@PRAXIS_PORT@@", "18080"))
                port = policy["network_policies"]["praxis_gateway"]["endpoints"][0]["port"]
                self.assertIs(type(port), int, "OpenShell schema requires an unsigned integer")

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
