#!/usr/bin/env python3
"""Provider configuration must preserve authentication and independent quotas."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/common"))
import provider_config as providers
import provider_manage as manager
from provider_manage import transaction


def source(scenario):
    name = "configs/remote-gateway/gateway.yaml" if scenario == "remote-gateway" else "configs/all-in-one/shared-gateway.yaml"
    return json.loads(subprocess.check_output(["ruby", "-ryaml", "-rjson", "-e",
                                              "puts YAML.load_file(ARGV[0]).to_json", str(ROOT / name)]))


class ProvidersTest(unittest.TestCase):
    def test_provider_wrapper_locks_the_selected_service_account(self):
        source = (ROOT / "scripts/common/providers").read_text()
        self.assertIn('exec 9>"$(gateway_lock_path "${SERVICE_USER}")"', source)
        self.assertNotIn("/run/lock/praxis-gateway.lock", source)

    def test_prompted_credentials_use_existing_secret_helper_stdin_only(self):
        execute = Mock()
        manager.create_cloud_secret("openai", "new-version", reader=lambda prompt: "synthetic-private-key", execute=execute)
        call = execute.call_args
        self.assertNotIn("synthetic-private-key", str(call.args))
        self.assertEqual(call.kwargs["input"], "synthetic-private-key")
        self.assertTrue(str(call.args[0][0]).endswith("scripts/common/secret-set"))

    def test_provider_update_refuses_to_reset_an_existing_custom_configuration(self):
        template = source("all-in-one")
        state = {"vllm": True, "vllm_endpoint": "", "openai_secret": "", "anthropic_secret": ""}
        installed = providers.render(template, vllm=True, openai=False, anthropic=False)
        installed["admin"]["address"] = "127.0.0.1:9999"
        with self.assertRaisesRegex(ValueError, "matching checkout"):
            manager.updated_config(template, installed, state, {**state, "openai_secret": "new-key"})
        self.assertEqual(installed["admin"]["address"], "127.0.0.1:9999")

    def test_unchanged_provider_state_does_not_require_restart(self):
        template = source("all-in-one")
        state = {"vllm": True, "vllm_endpoint": "", "openai_secret": "", "anthropic_secret": ""}
        installed = providers.render(template, vllm=True, openai=False, anthropic=False)
        self.assertIsNone(manager.updated_config(template, installed, state, state.copy()))

    def test_legacy_cloud_configuration_can_add_qwen_without_changing_listeners(self):
        template = source("all-in-one")
        state = {"vllm": False, "vllm_endpoint": "", "openai_secret": "openai-key", "anthropic_secret": "anthropic-key"}
        result = manager.updated_config(template, template, state, {**state, "vllm": True}, legacy=True)
        self.assertEqual(result["listeners"], template["listeners"])

    def test_legacy_state_without_a_remote_endpoint_still_normalizes(self):
        template = source("all-in-one")
        state = {"vllm": False, "openai_secret": "openai-key", "anthropic_secret": ""}
        result = manager.updated_config(template, template, state, {**state, "vllm": True}, legacy=True)
        self.assertEqual(result["listeners"], template["listeners"])

    def test_qwen_alone_needs_no_cloud_credentials_and_keeps_auth(self):
        for scenario in ("all-in-one", "remote-gateway"):
            original = source(scenario)
            config = providers.render(original, vllm=True, openai=False, anthropic=False)
            self.assertEqual(config["listeners"], original["listeners"])
            self.assertNotIn("credential_injection", json.dumps(config))
            for chain in config["filter_chains"]:
                filters = chain["filters"]
                routes = next(f["routes"] for f in filters if f["filter"] == "router")
                self.assertTrue(all(r["cluster"] == "vllm" and
                                    (r.get("path") or r.get("path_prefix")).startswith("/vllm/v1/") for r in routes))
                if scenario == "remote-gateway":
                    self.assertEqual(next(f for f in filters if f["filter"] == "policy"),
                                     {"filter": "policy", "config_path": "/etc/praxis/policy.yaml"})
                stripped = next(f["request_remove"] for f in filters if f["filter"] == "headers")
                self.assertIn("Authorization", stripped)
                self.assertIn("X-Api-Key", stripped)

    def test_remote_qwen_uses_exactly_one_private_upstream(self):
        template = source("all-in-one")
        endpoint = "10.0.1.10:8000"
        config = providers.render(template, vllm=True, openai=False, anthropic=False,
                                  vllm_endpoint=endpoint)
        cluster = next(cluster for filter in config["filter_chains"][0]["filters"]
                      if filter["filter"] == "load_balancer" for cluster in filter["clusters"]
                      if cluster["name"] == "vllm")
        self.assertEqual(cluster, {"name": "vllm", "endpoints": [endpoint],
                                   "http": {"authority": endpoint}})
        state = {"vllm": False, "vllm_endpoint": "", "openai_secret": "openai-key", "anthropic_secret": ""}
        selected = {**state, "vllm": True, "vllm_endpoint": endpoint}
        expected = providers.render(template, vllm=True, openai=True, anthropic=False,
                                    vllm_endpoint=endpoint)
        installed = providers.render(template, vllm=False, openai=True, anthropic=False)
        self.assertEqual(manager.updated_config(template, installed, state, selected), expected)
        with self.assertRaises(ValueError):
            providers.render(template, vllm=False, openai=True, anthropic=False,
                             vllm_endpoint=endpoint)
        with self.assertRaises(ValueError):
            providers.render(template, vllm=True, openai=False, anthropic=False,
                             vllm_endpoint="http://10.0.1.10:8000")
        with self.assertRaises(ValueError):
            providers.render(template, vllm=True, openai=False, anthropic=False,
                             vllm_endpoint="vllm.internal:8000")
        with self.assertRaises(ValueError):
            providers.render(template, vllm=True, openai=False, anthropic=False,
                             vllm_endpoint="8.8.8.8:8000")
        with self.assertRaises(ValueError):
            providers.render(template, vllm=True, openai=False, anthropic=False,
                             vllm_endpoint="10.010.1.10:8000")

    def test_explicit_empty_remote_endpoints_fail_instead_of_using_local_vllm(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/common/provider_config.py"),
                                 "--directory", "/unused", "--vllm", "--vllm-endpoint", ""],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("vllm endpoint must be RFC1918_IP:PORT", result.stderr)

        result = subprocess.run([sys.executable, str(ROOT / "scripts/common/provider_manage.py"),
                                 "enable", "vllm", "--vllm-endpoint", ""],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("vllm endpoint must be RFC1918_IP:PORT", result.stderr)

        result = subprocess.run(["bash", str(ROOT / "scripts/common/install"),
                                 "--vllm-endpoint", ""], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--vllm-endpoint may be given only once and requires RFC1918_IP:PORT", result.stderr)

    def test_remote_endpoint_cannot_be_selected_more_than_once(self):
        commands = [
            [sys.executable, str(ROOT / "scripts/common/provider_config.py"),
             "--directory", "/unused", "--vllm", "--vllm-endpoint", "10.0.1.10:8000",
             "--vllm-endpoint", "10.0.1.11:8000"],
            [sys.executable, str(ROOT / "scripts/common/provider_manage.py"),
             "enable", "vllm", "--vllm-endpoint", "10.0.1.10:8000",
             "--vllm-endpoint", "10.0.1.11:8000"],
            ["bash", str(ROOT / "scripts/common/install"),
             "--vllm-endpoint", "10.0.1.10:8000", "--vllm-endpoint", "10.0.1.11:8000"],
        ]
        for command in commands:
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("only once", result.stderr)

    def test_add_clouds_independently_keeps_qwen_and_valkey_namespaces(self):
        original = source("remote-gateway")
        for f in original["filter_chains"][0]["filters"]:
            if f["filter"] == "token_rate_limit":
                provider = f["rules"][0]["name"].split("-")[0]
                f["backend"] = {"kind": "valkey", "url": "${TOKEN_RATE_LIMIT_VALKEY_URL}",
                                "namespace": "secure-single-server:limits:" + provider}
        for openai, anthropic in ((True, False), (False, True), (True, True)):
            config = providers.render(original, vllm=True, openai=openai, anthropic=anthropic)
            filters = config["filter_chains"][0]["filters"]
            expected = {"vllm"} | ({"openai"} if openai else set()) | ({"anthropic"} if anthropic else set())
            self.assertEqual({c["name"] for f in filters if f["filter"] == "load_balancer" for c in f["clusters"]}, expected)
            credentials = {c["name"] for f in filters if f["filter"] == "credential_injection" for c in f["clusters"]}
            self.assertEqual(credentials, expected - {"vllm"})
            for f in filters:
                if f["filter"] == "token_rate_limit":
                    self.assertEqual(f["backend"]["kind"], "valkey")
                    self.assertTrue(f["backend"]["namespace"].startswith("secure-single-server:limits:"))
                    self.assertEqual(f["rules"][0]["capacity"], 1000000)

    def test_private_upstream_permission_is_enabled_only_for_local_inference(self):
        for scenario in ("all-in-one", "remote-gateway"):
            for vllm in (False, True):
                with self.subTest(scenario=scenario, vllm=vllm):
                    config = providers.render(source(scenario), vllm=vllm, openai=True, anthropic=True)
                    options = config.get("insecure_options", {})
                    self.assertEqual(options.get("allow_private_upstreams", False), vllm)
                    self.assertEqual(options.get("allow_private_endpoints", False), vllm)

    def test_reject_empty_set_and_leave_source_unchanged(self):
        original = source("all-in-one")
        before = copy.deepcopy(original)
        providers.render(original, vllm=True, openai=True, anthropic=True)
        self.assertEqual(original, before)
        with self.assertRaises(ValueError):
            providers.render(original, vllm=False, openai=False, anthropic=False)

    def test_cloud_only_optional_provider_keeps_disabled_listener_closed(self):
        config = providers.render(source("all-in-one"), vllm=False, openai=True, anthropic=False)
        disabled = config["filter_chains"][1]["filters"]
        self.assertEqual(disabled[-1], {"filter": "static_response", "status": 404, "body": "Provider disabled"})
        self.assertNotIn("credential_injection", json.dumps(disabled))

    def test_failed_activation_restores_files_manifest_and_previous_service(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, manifest, state = root / "gateway", root / "manifest", root / "providers.json"
            config.write_bytes(b"old config")
            config.chmod(0o640)
            manifest.write_bytes(b"old manifest")
            activate = Mock(side_effect=[RuntimeError("new configuration rejected"), None])
            with self.assertRaisesRegex(RuntimeError, "rejected"):
                transaction({config: b"new config", state: b"new state"}, manifest,
                            config.stat().st_gid, activate=activate)
            self.assertEqual(config.read_bytes(), b"old config")
            self.assertEqual(config.stat().st_mode & 0o777, 0o640)
            self.assertEqual(manifest.read_bytes(), b"old manifest")
            self.assertFalse(state.exists())
            self.assertEqual(activate.call_count, 2)

    def test_successful_activation_updates_only_changed_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, manifest, state = root / "gateway", root / "manifest", root / "providers.json"
            config.write_bytes(b"old config")
            manifest.write_text("oldhash  " + str(config) + "\nretainedhash  /etc/praxis/tls.pem\n")
            transaction({config: b"new config", state: b"new state"}, manifest,
                        config.stat().st_gid, activate=Mock())
            import hashlib
            self.assertIn(hashlib.sha256(b"new config").hexdigest(), manifest.read_text())
            self.assertIn("retainedhash  /etc/praxis/tls.pem", manifest.read_text())
            self.assertIn(str(state), manifest.read_text())


if __name__ == "__main__":
    unittest.main()
