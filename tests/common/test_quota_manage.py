"""Quota edits preserve providers, authentication, and managed upgrade state."""
import copy
import io
import json
import os
import shlex
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/common"))
import provider_config
import provider_manage
import quota_config
import quota_manage


def template(scenario="all-in-one"):
    name = ("configs/remote-gateway/gateway.yaml" if scenario == "remote-gateway"
            else "configs/all-in-one/shared-gateway.yaml")
    # Match the existing offline suite: PyYAML is installed on RHEL, optional locally.
    return json.loads(subprocess.check_output([
        "ruby", "-ryaml", "-rjson", "-e", "puts YAML.load_file(ARGV[0]).to_json", str(ROOT / name)]))


class QuotaManageTest(unittest.TestCase):
    def test_listing_prints_copyable_setting_commands_for_only_selected_settable_rules(self):
        source = provider_config.render(template(), vllm=True, openai=True, anthropic=True)
        report = quota_manage.listing(source, names=["vllm-openai-rolling-day"])
        output = quota_manage.format_listing(report)
        commands = [line.strip() for line in output.splitlines() if "quota-set --rule" in line]
        self.assertEqual(commands, ["sudo scripts/common/quota-set --rule vllm-openai-rolling-day --capacity 1000000"])
        self.assertIn("--apply", output)
        self.assertIn("sudo scripts/common/quota-status", output)
        # A custom rule name must remain a single literal shell argument.
        report["rules"][0]["rule"] = "local-$(touch /tmp/unwanted)"
        command = quota_manage.setting_commands(report)[0]
        self.assertEqual(shlex.split(command)[3], report["rules"][0]["rule"])
        report["rules"][0]["settable"] = False
        self.assertEqual(quota_manage.setting_commands(report), [])

    def test_list_shows_enabled_providers_and_only_installed_adjustable_rules(self):
        source = provider_config.render(template(), vllm=True, openai=False, anthropic=False)
        report = quota_manage.listing(source)
        self.assertEqual(report["providers"], [
            {"provider": "vllm", "enabled": True, "rules": 2, "settable": 2},
            {"provider": "openai", "enabled": False, "rules": 0, "settable": 0},
            {"provider": "anthropic", "enabled": False, "rules": 0, "settable": 0}])
        self.assertEqual(len(report["rules"]), 2)
        for row in report["rules"]:
            self.assertEqual(row["backend"], "memory")
            self.assertEqual(row["minimum_capacity"], 10000)
            self.assertEqual(row["capacity"], 1000000)
            self.assertTrue(row["settable"])
        text = quota_manage.format_listing(report)
        self.assertIn("disabled", text)
        self.assertIn("vllm-openai-rolling-day", text)
        self.assertIn("Minimum", text)
        self.assertNotIn("SECRET", text)

    def test_list_filters_match_apply_selectors_and_disabled_providers_are_visible(self):
        source = provider_config.render(template("remote-gateway"), vllm=True, openai=True, anthropic=False)
        for chain in source["filter_chains"]:
            for item in chain["filters"]:
                if item["filter"] == "token_rate_limit":
                    item["backend"] = {"kind": "valkey", "url": "private-credential"}
        report = quota_manage.listing(source, provider="vllm")
        self.assertEqual(len(report["providers"]), 1)
        self.assertEqual(len(report["rules"]), 2)
        self.assertTrue(all(row["backend"] == "valkey" for row in report["rules"]))
        self.assertNotIn("private-credential", json.dumps(report))
        self.assertEqual(quota_manage.listing(source, provider="anthropic")["rules"], [])
        report = quota_manage.listing(source, names=["openai-rolling-day"])
        self.assertEqual([row["rule"] for row in report["rules"]], ["openai-rolling-day"])
        with self.assertRaisesRegex(ValueError, "unknown"):
            quota_manage.listing(source, names=["missing"])

    def test_list_explains_rules_that_the_setter_cannot_adjust(self):
        source = provider_config.render(template(), vllm=True, openai=False, anthropic=False)
        rule = quota_config.rules(source)["vllm-openai-rolling-day"]
        rule["algorithm"] = "token_bucket"
        report = quota_manage.listing(source)
        self.assertFalse(report["rules"][0]["settable"])
        self.assertIsNone(report["rules"][0]["minimum_capacity"])
        self.assertIn("sliding_window", report["rules"][0]["reason"])
        self.assertEqual(report["providers"][0]["settable"], 1)
        with self.assertRaisesRegex(ValueError, "sliding_window"):
            quota_manage.plan(source, {}, 10000000, names=[rule["name"]])

    def test_list_cli_cannot_be_combined_with_a_mutation(self):
        args = quota_manage.parse_args(["--list", "--provider", "vllm", "--json"])
        self.assertTrue(args.list)
        self.assertIsNone(args.capacity)
        self.assertEqual(quota_manage.parse_args(["--rule", "a", "--capacity", "10000"]).rule, ["a"])
        for args in (["--list", "--apply"], ["--list", "--capacity", "10000"],
                     ["--provider", "vllm"], ["--capacity", "10000"],
                     ["--provider", "vllm", "--capacity", "10000", "--json"]):
            with self.subTest(args=args), redirect_stdout(io.StringIO()), \
                    patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
                quota_manage.parse_args(args)

    def test_list_main_is_read_only_and_does_not_need_metrics_or_a_running_service(self):
        source = provider_config.render(template(), vllm=True, openai=False, anthropic=False)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "shared-gateway.yaml").write_text(json.dumps(source))
            (root / "shared-gateway.profile").write_text("memory")
            (root / "gateway.scenario").write_text("all-in-one")
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            output = io.StringIO()
            with patch.dict(os.environ, PRAXIS_CONFIG_DIR=directory), \
                    patch.object(sys, "argv", ["quota-set", "--list", "--json"]), \
                    patch.dict(sys.modules, {"yaml": SimpleNamespace(safe_load=json.loads)}), \
                    patch.object(os, "geteuid", return_value=0), \
                    patch.object(quota_manage, "transaction") as tx, \
                    patch.object(quota_manage.pwd, "getpwnam") as account, redirect_stdout(output):
                quota_manage.main()
                tx.assert_not_called()
                account.assert_not_called()
            self.assertEqual(json.loads(output.getvalue())["profile"], "memory")
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})

    def test_provider_selection_changes_only_its_capacities_in_both_scenarios(self):
        for scenario in ("all-in-one", "remote-gateway"):
            source = provider_config.render(template(scenario), vllm=True, openai=True, anthropic=True)
            before = copy.deepcopy(source)
            for provider, count in (("vllm", 2), ("openai", 1), ("anthropic", 1)):
                overrides, rows = quota_manage.plan(source, {}, 10000000, provider=provider)
                result = quota_config.apply(source, overrides)
                self.assertEqual(len(rows), count)
                for name, rule in quota_config.rules(result).items():
                    self.assertEqual(rule["capacity"], 10000000 if name in overrides else 1000000)
                    rule["capacity"] = 1000000
                self.assertEqual(result, before)
            self.assertEqual(source, before)

    def test_exact_rule_selection_preserves_other_overrides_and_disabled_providers(self):
        source = provider_config.render(template(), vllm=True, openai=False, anthropic=False)
        old = {"openai-rolling-day": 3000000, "vllm-anthropic-rolling-day": 2000000}
        overrides, rows = quota_manage.plan(quota_config.apply(source, old), old, 5000000,
                                           names=["vllm-openai-rolling-day"])
        self.assertEqual(overrides, {**old, "vllm-openai-rolling-day": 5000000})
        self.assertEqual(len(rows), 1)

    def test_rejects_unknown_disabled_ambiguous_and_invalid_capacities(self):
        source = provider_config.render(template(), vllm=True, openai=False, anthropic=False)
        for capacity in (0, -1, True, 1.5, "1000000", 9999, 2**64):
            with self.subTest(capacity=capacity), self.assertRaises(ValueError):
                quota_manage.plan(source, {}, capacity, provider="vllm")
        for kwargs in ({"provider": "openai"}, {"names": ["missing"]},
                       {"names": ["vllm-openai-rolling-day", "missing"]}):
            with self.assertRaises(ValueError):
                quota_manage.plan(source, {}, 10000000, **kwargs)
        source["filter_chains"] *= 2
        with self.assertRaisesRegex(ValueError, "unique"):
            quota_manage.plan(source, {}, 10000000, provider="vllm")

    def test_provider_add_remove_reenable_retains_only_explicit_quota_overrides(self):
        for scenario in ("all-in-one", "remote-gateway"):
            base = template(scenario)
            state = {"vllm": True, "openai_secret": "", "anthropic_secret": ""}
            overrides = {"vllm-openai-rolling-day": 10000000, "openai-rolling-day": 2000000}
            config = quota_config.apply(provider_config.render(base, vllm=True, openai=False,
                                                                anthropic=False), overrides)
            for selected in ({**state, "openai_secret": "key"},
                             {**state, "vllm": False, "openai_secret": "key"},
                             {**state, "openai_secret": "key", "anthropic_secret": "another"}):
                config = provider_manage.updated_config(base, config, state, selected, overrides=overrides)
                expected = quota_config.apply(provider_config.render(base, vllm=selected["vllm"],
                    openai=bool(selected["openai_secret"]), anthropic=bool(selected["anthropic_secret"])), overrides)
                self.assertEqual(config, expected)
                state = selected
            config["admin"]["address"] = "127.0.0.1:9999"
            with self.assertRaisesRegex(ValueError, "matching checkout"):
                provider_manage.updated_config(base, config, state, state, overrides=overrides)

    def test_legacy_cloud_config_retains_override_on_first_provider_change(self):
        base = template()
        state = {"vllm": False, "openai_secret": "key", "anthropic_secret": "another"}
        overrides = {"openai-rolling-day": 2000000}
        result = provider_manage.updated_config(base, quota_config.apply(base, overrides), state,
                    {**state, "vllm": True}, legacy=True, overrides=overrides)
        self.assertEqual(quota_config.rules(result)["openai-rolling-day"]["capacity"], 2000000)
        self.assertEqual(quota_config.rules(result)["vllm-openai-rolling-day"]["capacity"], 1000000)

    def test_preview_and_unchanged_apply_never_write_or_restart(self):
        source = provider_config.render(template(), vllm=True, openai=False, anthropic=False)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "shared-gateway.yaml"
            path.write_text(json.dumps(source))
            original = path.read_bytes()
            for apply, capacity in ((False, 10000000), (True, 1000000)):
                with patch.object(quota_manage, "transaction") as tx, redirect_stdout(io.StringIO()):
                    quota_manage.change(root, source, {}, capacity, os.getgid(), provider="vllm", apply=apply)
                    tx.assert_not_called()
                self.assertEqual(path.read_bytes(), original)
                self.assertFalse((root / "quota-overrides.json").exists())

    def test_apply_changes_config_and_overrides_together_and_failure_rolls_back(self):
        for fail in (False, True):
            source = provider_config.render(template(), vllm=True, openai=True, anthropic=True)
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path, manifest = root / "shared-gateway.yaml", root / "shared-gateway.manifest"
                path.write_text(json.dumps(source))
                manifest.write_text("old  " + str(path) + "\nkept  /etc/praxis/tls.pem\n")
                previous = (path.read_bytes(), manifest.read_bytes())
                activation = Mock(side_effect=[RuntimeError("activation failed"), None] if fail else None)
                def tx(changes, manifest, gid, **kwargs):
                    return provider_manage.transaction(changes, manifest, gid, activate=activation)
                with patch.object(quota_manage, "transaction", side_effect=tx), redirect_stdout(io.StringIO()):
                    if fail:
                        with self.assertRaisesRegex(RuntimeError, "activation failed"):
                            quota_manage.change(root, source, {}, 10000000, os.getgid(), provider="vllm", apply=True)
                        self.assertEqual((path.read_bytes(), manifest.read_bytes()), previous)
                        self.assertFalse((root / "quota-overrides.json").exists())
                    else:
                        quota_manage.change(root, source, {}, 10000000, os.getgid(), provider="vllm", apply=True)
                        self.assertEqual(json.loads(path.read_text()), quota_config.apply(source,
                                            json.loads((root / "quota-overrides.json").read_text())))
                        self.assertIn("kept  /etc/praxis/tls.pem", manifest.read_text())
                        self.assertIn(str(root / "quota-overrides.json"), manifest.read_text())
                        self.assertEqual(activation.call_count, 1)

    def test_bad_saved_overrides_fail_before_rendering(self):
        for invalid in ([], {"a": True}, {"a": 0}, {"a": {"capacity": 10}}, {"": 1000000}):
            with self.assertRaises(ValueError):
                quota_config.apply(template(), invalid)

    def test_upgrade_renderer_loads_saved_capacities_after_rerendering_providers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, saved = root / "shared-gateway.yaml", root / "quota-overrides.json"
            saved.write_text('{"vllm-openai-rolling-day": 10000000}')
            for scenario in ("all-in-one", "remote-gateway"):
                for cloud in (False, True):
                    source = provider_config.render(template(scenario), vllm=True, openai=cloud, anthropic=cloud)
                    path.write_text(json.dumps(source))
                    with patch.object(sys, "argv", ["quota_config.py", "--config", str(path), "--overrides", str(saved)]), \
                            patch.dict(sys.modules, {"yaml": SimpleNamespace(safe_load=json.loads)}):
                        quota_config.main()
                    result = json.loads(path.read_text())
                    self.assertEqual(quota_config.rules(result)["vllm-openai-rolling-day"]["capacity"], 10000000)
                    self.assertEqual(quota_config.rules(result)["vllm-anthropic-rolling-day"]["capacity"], 1000000)
                    if cloud:
                        self.assertEqual(quota_config.rules(result)["openai-rolling-day"]["capacity"], 1000000)
                    self.assertEqual(saved.read_text(), '{"vllm-openai-rolling-day": 10000000}')


if __name__ == "__main__":
    unittest.main()
