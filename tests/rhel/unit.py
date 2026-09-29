#!/usr/bin/env python3
"""Offline regression checks for test-bundle boundaries and real CLI fixtures."""
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from argparse import Namespace
from contextlib import redirect_stdout

import run as runner
import harness_provider as harness
import host
from integration import ran_tests
import integration


class RunnerTest(unittest.TestCase):
    def test_failed_command_streams_and_retains_output(self):
        terminal, log = io.StringIO(), io.StringIO()
        with redirect_stdout(terminal):
            code = runner.logged([sys.executable, "-c", "print('failure details'); raise SystemExit(7)"], log)
        self.assertEqual(code, 7)
        self.assertEqual(log.getvalue(), "failure details\n")
        self.assertEqual(terminal.getvalue(), log.getvalue())

    def test_bundle_excludes_workstation_material(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("configs", "scripts", "tests", "openshell", ".state", ".git"):
                (root / name).mkdir()
                (root / name / "included.txt").write_text(name)
            for name in ("caller.secret", "credentials.local", "cache.pyc"):
                (root / "tests" / name).write_text("must stay local")
            with patch.object(runner, "ROOT", root):
                data, manifest = runner.bundle()
            with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                self.assertEqual(set(archive.getnames()), set(manifest))
                self.assertEqual(len(manifest), 4)
                self.assertTrue(all(len(value) == 64 for value in manifest.values()))

    def test_bundle_refuses_symlink_to_private_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "configs").mkdir()
            private = root / "private.key"
            private.write_text("private")
            (root / "configs/key").symlink_to(private)
            with patch.object(runner, "ROOT", root), self.assertRaises(ValueError):
                runner.bundle()


class HarnessTest(unittest.TestCase):
    def test_opencode_failed_tool_and_claude_nonmessage_events_are_not_passes(self):
        for code in (0, 1):
            log = json.dumps({"type": "tool_use", "part": {"tool": "bash", "state": {
                "status": "completed", "input": {"command": "python3 -m unittest -v"},
                "metadata": {"exit": code}}}})
            self.assertEqual(ran_tests("opencode", log), code == 0)
        self.assertFalse(ran_tests("claude", '{"type":"error","message":"unittest failed"}'))

    def test_timeout_stops_process_group_and_keeps_partial_output(self):
        with patch.object(integration.os, "killpg", wraps=os.killpg) as kill:
            with self.assertRaises(subprocess.TimeoutExpired) as error:
                integration.run_captured([sys.executable, "-u", "-c",
                    "import time; print('partial evidence'); time.sleep(60)"], timeout=0.3)
            self.assertIn("partial evidence", error.exception.output)
            self.assertTrue(any(call.args[1] == signal.SIGTERM for call in kill.call_args_list))

    def test_user_environment_is_not_put_in_process_arguments(self):
        with patch.object(integration.pwd, "getpwnam", return_value=Namespace(pw_dir="/home/test")), \
             patch.object(integration, "run_captured") as execute:
            integration.user_command("example", environment={"AUTH_TOKEN": "private-caller"})
        self.assertNotIn("private-caller", str(execute.call_args.args))
        self.assertTrue(Path(execute.call_args.args[0][0]).is_absolute())
        self.assertEqual(execute.call_args.kwargs["env"]["AUTH_TOKEN"], "private-caller")

    def test_model_claim_or_failed_command_is_not_a_successful_test_run(self):
        self.assertFalse(ran_tests("codex", '{"type":"item.completed","item":{"type":"agent_message","text":"unittest passed"}}'))
        for code in (0, 1):
            log = json.dumps({"type": "item.completed", "item": {"type": "command_execution",
                "command": "python3 -m unittest -v", "exit_code": code}})
            self.assertEqual(ran_tests("codex", log), code == 0)

    def test_real_tool_arguments_are_preserved_in_streams(self):
        for path, name in (("/v1/responses", "exec_command"),
                           ("/v1/chat/completions", "bash"), ("/v1/messages", "Bash")):
            body = {"tools": [{"name": name}]}
            with patch.object(harness.provider, "continuation", harness.continuation):
                response = harness.completion(path, body)
            stream = b"".join(harness.provider.events(path, response)).decode()
            self.assertIn(name, stream)
            self.assertIn("test_add.py", stream)
            self.assertIn("python3", stream)

    def test_prompt_or_failed_tool_cannot_complete_task(self):
        message = {"role": "user", "content": harness.MARKER}
        self.assertFalse(harness.continuation("/v1/messages", {"messages": [message]}))
        result = {"type": "tool_result", "tool_use_id": "call_fixture",
                  "content": harness.MARKER, "is_error": True}
        body = {"messages": [{"role": "user", "content": [result]}]}
        self.assertFalse(harness.continuation("/v1/messages", body))
        result["is_error"] = False
        self.assertTrue(harness.continuation("/v1/messages", body))

    def test_continuation_returns_final_text_instead_of_another_tool(self):
        body = {"tools": [{"name": "Bash"}], "messages": [{"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "call_fixture", "content": harness.MARKER}]}]}
        with patch.object(harness.provider, "continuation", harness.continuation):
            response = harness.completion("/v1/messages", body)
        self.assertEqual(response["content"], [{"type": "text", "text": harness.MARKER}])


class ProfileTest(unittest.TestCase):
    def test_remote_transition_preserves_identity_with_private_installer_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)
            for name in ("tls.pem", "tls-key.pem", "jwt-public.pem"):
                (config / name).write_text(name)
                (config / name).chmod(0o640)
            def install(*command):
                for flag, name in (("--tls-cert", "tls.pem"), ("--tls-key", "tls-key.pem"),
                                   ("--jwt-public-key", "jwt-public.pem")):
                    path = Path(command[command.index(flag) + 1])
                    self.assertEqual(path.read_bytes(), (config / name).read_bytes())
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                    self.assertEqual((config / name).stat().st_mode & 0o777, 0o640)
            with patch.object(host, "STATE", config), patch.object(host, "run", side_effect=install) as execute:
                host.restore_production(Namespace(scenario="remote-gateway", profile="memory"), {}, None, config)
                execute.assert_called_once()

    def test_mock_resume_recovers_unmounted_synthetic_secrets(self):
        args = Namespace(scenario="all-in-one", profile="memory")
        secrets = {"OPENAI_API_KEY": "praxis-openai-api-key-smoke-test",
                   "ANTHROPIC_API_KEY": "praxis-anthropic-api-key-smoke-test"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = dict(scenario=args.scenario, profile=args.profile, mock=True, secrets=secrets)
            (root / "state.json").write_text(json.dumps(state))
            with patch.object(host, "STATE", root), patch.object(host, "service"):
                self.assertEqual(host.mock_secrets(args, {}), secrets)
                state["mock"] = False
                (root / "state.json").write_text(json.dumps(state))
                with self.assertRaisesRegex(ValueError, "mock-again"):
                    host.mock_secrets(args, {})

    def test_starting_a_new_mock_attempt_invalidates_both_pass_markers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("baseline-memory.json", "providers-memory.json"):
                (root / name).write_text("old pass")
            with patch.object(host, "STATE", root):
                host.invalidate_mock_results("memory")
            self.assertEqual(list(root.iterdir()), [])

    def test_switch_rejects_unowned_or_wrong_scenario_before_mutation(self):
        for state in ({"scenario": "remote-gateway", "profile": "memory", "mock": True},
                      {"scenario": "all-in-one", "profile": "memory", "mock": False}):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "state.json").write_text(json.dumps(state))
                with patch.object(host, "STATE", root), patch.object(host, "run") as execute:
                    with self.assertRaises(ValueError):
                        host.switch_profile(Namespace(scenario="all-in-one", profile="valkey"))
                    execute.assert_not_called()

    def test_switch_verifies_before_uninstall_and_keeps_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = {"scenario": "all-in-one", "profile": "memory", "mock": True}
            (root / "state.json").write_text(json.dumps(old))
            calls = []
            with patch.object(host, "STATE", root), \
                 patch.object(host, "installed", side_effect=lambda args: calls.append("verify")), \
                 patch.object(host, "service", side_effect=lambda *args: calls.append("stop")), \
                 patch.object(host, "run", side_effect=lambda *args: calls.append(args)):
                host.switch_profile(Namespace(scenario="all-in-one", profile="valkey"))
            self.assertEqual(calls, ["verify", "stop", ("scripts/common/uninstall",)])
            self.assertFalse((root / "state.json").exists())
            self.assertEqual(json.loads(next(root.glob("state-memory-*.json")).read_text()), old)


if __name__ == "__main__":
    unittest.main()
