#!/usr/bin/env python3
"""Offline contracts for the OpenCode PR-candidate queue example."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


class PrQueueTests(unittest.TestCase):
    def run_queue(self, arguments):
        return subprocess.run(
            [str(ROOT / "openshell/harnesses/opencode/pr-queue/queue.sh"), *arguments],
            capture_output=True, text=True, timeout=10)

    def run_queue_with_fake_ssh(self, metadata, patch):
        with tempfile.TemporaryDirectory() as directory:
            ssh = Path(directory) / "ssh"
            ssh.write_text(r"""#!/usr/bin/env bash
set -euo pipefail
remote="${@: -1}"
case "${remote}" in
  "mkdir"*"cat >"*|"cat >"*)
    printf '\n=== %s ===\n' "${remote}" >>"${FAKE_UPLOAD_CAPTURE}"
    cat >>"${FAKE_UPLOAD_CAPTURE}"
  ;;
  "mkdir"*) ;;
  "cd "*) printf '%s\n' "${remote}" ;;
  "cat"*)
    case "${remote}" in
      *opencode.json\") printf '%s\n' '{"model":"praxis/gpt-6.1-sol"}' ;;
      *metadata.json\") printf '%s\n' "${FAKE_METADATA_JSON}" ;;
      *) exit 2 ;;
    esac
    ;;
  "printf"*) printf '%s\n' "${remote}" ;;
  "test"*)
    case "${remote}" in
      *metadata.json\"|*report.md\") exit 0 ;;
      *changes.patch\") [[ -n "${FAKE_PATCH}" ]] ;;
      *) exit 2 ;;
    esac
    ;;
  *) printf 'unexpected ssh command: %s\\n' "${remote}" >&2; exit 2 ;;
esac
""")
            ssh.chmod(0o755)
            environment = {
                **os.environ,
                "PATH": f"{directory}:{os.environ['PATH']}",
                "OPENSHELL_BIN": "/bin/true",
                "FAKE_METADATA_JSON": metadata,
                "FAKE_PATCH": patch,
                "FAKE_UPLOAD_CAPTURE": str(Path(directory) / "uploads"),
            }
            result = subprocess.run(
                [str(ROOT / "openshell/harnesses/opencode/pr-queue/queue.sh"),
                 "--repo", "owner/repo", "--message", "test", "--timeout", "60"],
                capture_output=True, text=True, timeout=10, env=environment)
            return result, (Path(directory) / "uploads").read_text()

    def valid_metadata(self, status):
        return json.dumps({
            "repository": "https://github.com/owner/repo.git",
            "task_kind": "prompt",
            "prompt_identifier": "prompt-1",
            "base_ref": "main",
            "base_commit": "0" * 40,
            "branch": "opencode/prompt-1",
            "proposed_pr_title": "Example",
            "summary": "Example change",
            "test_results": [],
            "known_risks": [],
            "status": status,
        })

    def run_collect_with_fake_ssh(self, status, include_patch):
        with tempfile.TemporaryDirectory() as directory:
            sandbox_home = Path(directory) / "sandbox-home"
            task = sandbox_home / "pr-queue" / "artifacts" / "task-1"
            (task / "repository").mkdir(parents=True)
            (task / "repository" / "regular.txt").write_text("safe\n")
            (task / "repository" / "symlink").symlink_to("/tmp")
            (task / "metadata.json").write_text(self.valid_metadata(status))
            (task / "report.md").write_text("Example report\n")
            if include_patch:
                (task / "changes.patch").write_text("diff --git a/example b/example\n")

            ssh = Path(directory) / "ssh"
            ssh.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "remote=\"${@: -1}\"\n"
                "export HOME=\"$FAKE_SANDBOX_HOME\"\n"
                "eval \"$remote\"\n")
            ssh.chmod(0o755)
            destination = Path(directory) / "collected"
            result = subprocess.run(
                [str(ROOT / "openshell/harnesses/opencode/pr-queue/collect.sh"),
                 "--name", "test-sandbox", "--dest", str(destination)],
                capture_output=True, text=True, timeout=10,
                env={**os.environ,
                     "PATH": f"{directory}:{os.environ['PATH']}",
                     "OPENSHELL_BIN": "/bin/true",
                     "FAKE_SANDBOX_HOME": str(sandbox_home)})
            task = destination / "task-1"
            checks = {
                "destination_exists": destination.exists(),
                "metadata": (task / "metadata.json").is_file(),
                "report": (task / "report.md").is_file(),
                "patch": (task / "changes.patch").exists(),
                "regular_file": (task / "repository" / "regular.txt").is_file(),
                "symlink": ((task / "repository" / "symlink").exists() or
                            (task / "repository" / "symlink").is_symlink()),
            }
            return result, checks

    def test_argument_validation_fails_before_gateway_use(self):
        cases = [
            [],
            ["--repo", "not-a-repository", "--issue", "1"],
            ["--repo", "owner/repo"],
            ["--repo", "owner/repo", "--issue", "0"],
            ["--repo", "owner/repo", "--issue", "1", "--timeout", "59"],
            ["--repo", "owner/repo", "--issue", "1", "--timeout", "14401"],
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = self.run_queue(arguments)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("error:", result.stderr)

    def test_collect_rejects_existing_destination_before_ssh(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "existing"
            destination.mkdir()
            result = subprocess.run(
                [str(ROOT / "openshell/harnesses/opencode/pr-queue/collect.sh"),
                 "--name", "unused", "--dest", str(destination)],
                capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("destination already exists", result.stderr)

    def test_collect_rejects_successful_task_without_patch_before_extraction(self):
        result, checks = self.run_collect_with_fake_ssh("success", False)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(
            "successful task task-1 did not produce non-empty changes.patch",
            result.stderr)
        self.assertFalse(checks["destination_exists"])

    def test_collect_accepts_failed_task_and_excludes_repository_symlinks(self):
        result, checks = self.run_collect_with_fake_ssh("failed", False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(checks["metadata"])
        self.assertTrue(checks["report"])
        self.assertFalse(checks["patch"])
        self.assertTrue(checks["regular_file"])
        self.assertFalse(checks["symlink"])

    def test_queue_validates_patch_only_for_successful_tasks(self):
        valid_metadata = json.dumps({
            "repository": "https://github.com/owner/repo.git",
            "task_kind": "prompt",
            "prompt_identifier": "prompt-1",
            "base_ref": "origin/main",
            "base_commit": "0" * 40,
            "branch": "opencode/prompt-1",
            "proposed_pr_title": "Example",
            "summary": "Example change",
            "test_results": [],
            "known_risks": [],
        })

        failed_result, failed_uploads = self.run_queue_with_fake_ssh(
            json.dumps({**json.loads(valid_metadata), "status": "failed"}), "")
        self.assertNotEqual(failed_result.returncode, 0)
        self.assertIn("OpenCode turn reported failure", failed_result.stderr)
        self.assertNotIn("did not produce changes.patch", failed_result.stderr)

        missing_patch_result, missing_patch_uploads = self.run_queue_with_fake_ssh(
            json.dumps({**json.loads(valid_metadata), "status": "success"}), "")
        self.assertNotEqual(missing_patch_result.returncode, 0)
        self.assertIn("did not produce changes.patch", missing_patch_result.stderr)

        successful_result, successful_uploads = self.run_queue_with_fake_ssh(
            json.dumps({**json.loads(valid_metadata), "status": "success"}),
            "diff --git a/example b/example\n")
        self.assertEqual(successful_result.returncode, 0, successful_result.stderr)
        self.assertIn("Completed PR candidate", successful_result.stdout)
        self.assertIn("opencode run --pure --auto", successful_result.stdout)
        self.assertIn("</dev/null", successful_result.stdout)
        self.assertIn("repository/.", successful_result.stdout)
        self.assertIn("changes.patch", successful_result.stdout)
        self.assertIn("metadata.template.json", successful_result.stdout)
        self.assertIn("never\\ completed", successful_result.stdout)
        self.assertIn("--model praxis/gpt-6.1-sol", successful_result.stdout)
        self.assertIn("agent-instructions.md", successful_uploads)
        self.assertIn("task.md", successful_uploads)
        self.assertIn("Repository: https://github.com/owner/repo.git", successful_uploads)
        self.assertIn("Task kind: prompt", successful_uploads)
        self.assertIn("Task kind: prompt", failed_uploads)
        self.assertIn("Repository: https://github.com/owner/repo.git", missing_patch_uploads)

        incomplete_result, incomplete_uploads = self.run_queue_with_fake_ssh(
            '{"status":"success"}', "diff --git a/example b/example\n")
        self.assertNotEqual(incomplete_result.returncode, 0)
        self.assertIn("metadata field must be a non-empty string", incomplete_result.stderr)
        self.assertIn("task.md", incomplete_uploads)

    def test_harness_ssh_timeout_kills_stalled_ssh(self):
        with tempfile.TemporaryDirectory() as directory:
            ssh = Path(directory) / "ssh"
            ssh.write_text("#!/usr/bin/env bash\nexec sleep 5\n")
            ssh.chmod(0o755)
            command = (
                "source openshell/scripts/harness-lib.sh; "
                "OPENSHELL_BIN=/bin/true harness_ssh_timeout test-sandbox 1 remote-command"
            )
            started = time.monotonic()
            result = subprocess.run(
                ["bash", "-c", command], capture_output=True, text=True,
                timeout=4, env={**os.environ, "PATH": f"{directory}:{os.environ['PATH']}"})
            elapsed = time.monotonic() - started

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("sandbox SSH operation timed out", result.stderr)
            self.assertLess(elapsed, 3)

    def test_harness_ssh_timeout_preserves_stdin(self):
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "captured"
            ssh = Path(directory) / "ssh"
            ssh.write_text("#!/usr/bin/env bash\ncat >\"${FAKE_STDIN_CAPTURE}\"\n")
            ssh.chmod(0o755)
            command = (
                "source openshell/scripts/harness-lib.sh; "
                "OPENSHELL_BIN=/bin/true harness_ssh_timeout test-sandbox 5 remote-command"
            )
            result = subprocess.run(
                ["bash", "-c", command], input="expected payload\n",
                capture_output=True, text=True, timeout=4,
                env={**os.environ,
                     "PATH": f"{directory}:{os.environ['PATH']}",
                     "FAKE_STDIN_CAPTURE": str(capture)})

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(capture.read_text(), "expected payload\n")

    def test_safe_extractor_allows_files_and_rejects_traversal(self):
        extractor = ROOT / "openshell/scripts/extract-safe-tar.py"
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as bundle:
            directory = tarfile.TarInfo("nested")
            directory.type = tarfile.DIRTYPE
            bundle.addfile(directory)
            payload = b"safe\n"
            member = tarfile.TarInfo("nested/report.md")
            member.size = len(payload)
            bundle.addfile(member, io.BytesIO(payload))
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "extracted"
            destination.mkdir()
            result = subprocess.run([sys.executable, str(extractor), str(destination)],
                                    input=archive.getvalue(), capture_output=True, check=True)
            self.assertIn(b"extracted 1 files", result.stdout)
            self.assertEqual((destination / "nested/report.md").read_bytes(), payload)
            self.assertEqual((destination / "nested/report.md").stat().st_mode & 0o777, 0o644)

        malicious = io.BytesIO()
        with tarfile.open(fileobj=malicious, mode="w") as bundle:
            member = tarfile.TarInfo("../escape.txt")
            member.size = 0
            bundle.addfile(member, io.BytesIO(b""))
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "extracted"
            destination.mkdir()
            result = subprocess.run([sys.executable, str(extractor), str(destination)],
                                    input=malicious.getvalue().decode(), capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsafe tar member name", result.stderr)
            self.assertFalse((Path(directory) / "escape.txt").exists())

    def test_safe_extractor_rejects_absolute_names_and_member_limit(self):
        extractor = ROOT / "openshell/scripts/extract-safe-tar.py"
        absolute = io.BytesIO()
        with tarfile.open(fileobj=absolute, mode="w") as bundle:
            member = tarfile.TarInfo("/tmp/payload")
            member.size = 0
            bundle.addfile(member, io.BytesIO(b""))

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "extracted"
            destination.mkdir()
            result = subprocess.run(
                [sys.executable, str(extractor), str(destination)],
                input=absolute.getvalue().decode(), capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsafe tar member name", result.stderr)
            self.assertEqual(list(destination.iterdir()), [])

        too_many_members = io.BytesIO()
        with tarfile.open(fileobj=too_many_members, mode="w") as bundle:
            for name in ("first.txt", "second.txt"):
                member = tarfile.TarInfo(name)
                member.size = 0
                bundle.addfile(member, io.BytesIO(b""))

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "extracted"
            destination.mkdir()
            result = subprocess.run(
                [sys.executable, str(extractor), str(destination), "--max-members", "1"],
                input=too_many_members.getvalue().decode(), capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exceeds member count limit", result.stderr)
            self.assertEqual(list(destination.iterdir()), [])

    def test_safe_extractor_preserves_existing_directory_modes(self):
        extractor = ROOT / "openshell/scripts/extract-safe-tar.py"
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as bundle:
            directory = tarfile.TarInfo("nested")
            directory.type = tarfile.DIRTYPE
            bundle.addfile(directory)
            payload = b"safe\n"
            member = tarfile.TarInfo("nested/report.md")
            member.size = len(payload)
            bundle.addfile(member, io.BytesIO(payload))

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "extracted"
            nested = destination / "nested"
            nested.mkdir(parents=True)
            nested.chmod(0o700)
            result = subprocess.run(
                [sys.executable, str(extractor), str(destination)],
                input=archive.getvalue(), capture_output=True, check=True)

            self.assertIn(b"extracted 1 files", result.stdout)
            self.assertEqual((nested / "report.md").read_bytes(), b"safe\n")
            self.assertEqual(nested.stat().st_mode & 0o777, 0o700)

    def test_safe_extractor_accepts_collector_root_directory_entry(self):
        extractor = ROOT / "openshell/scripts/extract-safe-tar.py"
        with tempfile.TemporaryDirectory() as source_directory:
            source = Path(source_directory)
            (source / "nested").mkdir()
            (source / "nested" / "report.md").write_bytes(b"safe\n")
            archive = subprocess.run(
                ["tar", "-C", source_directory, "-cf", "-", "."],
                capture_output=True, check=True,
                env={**os.environ, "COPYFILE_DISABLE": "1"}).stdout

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "extracted"
            destination.mkdir()
            result = subprocess.run(
                [sys.executable, str(extractor), str(destination)],
                input=archive, capture_output=True, check=True)
            self.assertIn(b"extracted 1 files", result.stdout)
            self.assertEqual(
                (destination / "nested" / "report.md").read_bytes(), b"safe\n")

    def test_safe_extractor_enforces_byte_limits_and_rolls_back(self):
        extractor = ROOT / "openshell/scripts/extract-safe-tar.py"
        cases = [
            ("--max-file-bytes", "3"),
            ("--max-total-bytes", "5"),
        ]
        for limit in cases:
            with self.subTest(limit=limit):
                archive = io.BytesIO()
                with tarfile.open(fileobj=archive, mode="w") as bundle:
                    first = b"12345"
                    member = tarfile.TarInfo("nested/first.txt")
                    member.size = len(first)
                    bundle.addfile(member, io.BytesIO(first))
                    second = b"67890"
                    member = tarfile.TarInfo("nested/second.txt")
                    member.size = len(second)
                    bundle.addfile(member, io.BytesIO(second))

                with tempfile.TemporaryDirectory() as directory:
                    destination = Path(directory) / "extracted"
                    destination.mkdir()
                    result = subprocess.run(
                        [sys.executable, str(extractor), str(destination), *limit],
                        input=archive.getvalue(), capture_output=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(b"exceeds", result.stderr)
                    self.assertEqual(list(destination.iterdir()), [])

    def test_profile_and_catalog_are_minimal_and_connected(self):
        policy_path = ROOT / "configs/openshell-praxis/profiles/pr-queue/policy.yaml"
        policy = yaml.safe_load(policy_path.read_text()
                                .replace("@@PRAXIS_PORT@@", "18080")
                                .replace("@@PRAXIS_API_PREFIX@@", ""))
        self.assertEqual(set(policy["network_policies"]),
                         {"praxis_gateway", "github_api", "github_git"})
        praxis_rules = policy["network_policies"]["praxis_gateway"]["endpoints"][0]["rules"]
        self.assertEqual([rule["allow"] for rule in praxis_rules][-1],
                         {"method": "POST", "path": "/v1/responses"})
        self.assertEqual(policy["network_policies"]["github_api"]["endpoints"][0]["access"],
                         "read-only")
        git_rules = policy["network_policies"]["github_git"]["endpoints"][0]["rules"]
        self.assertEqual(git_rules[-1]["allow"],
                         {"method": "POST", "path": "/**/git-upload-pack"})

        catalog = json.loads((ROOT / "configs/templates/opencode.json").read_text())
        entry = next(item for item in catalog["templates"]
                     if item["harness"] == "opencode" and item["profile"] == "pr-queue")
        self.assertEqual(entry["backend"], "cloud")
        self.assertEqual(entry["config_dir"], "configs/openshell-praxis")

    def test_pr_queue_bootc_selection_requires_integrated_config(self):
        command = [
            str(ROOT / "openshell/scripts/template.sh"), "select",
            "--harness", "opencode", "--profile", "pr-queue",
            "--backend", "cloud",
        ]
        environment = {
            **os.environ,
            "ODH_CODEX_IMAGE": "quay.io/test/codex@sha256:" + "c" * 64,
            "ODH_OPENCLAW_IMAGE": "quay.io/test/openclaw@sha256:" + "b" * 64,
            "ODH_OPENCODE_IMAGE": "quay.io/test/opencode@sha256:" + "a" * 64,
        }

        without_config = subprocess.run(
            command, capture_output=True, text=True, timeout=10, env=environment)
        self.assertNotEqual(without_config.returncode, 0)
        self.assertIn("no template for opencode/pr-queue/standalone",
                      without_config.stderr)

        with_config = subprocess.run(
            command + ["--config", str(ROOT / "configs/openshell-praxis")],
            capture_output=True, text=True, timeout=10, env=environment)
        self.assertEqual(with_config.returncode, 0, with_config.stderr)
        selection = with_config.stdout.splitlines()
        self.assertEqual(selection[0], "cloud")
        self.assertEqual(selection[2], str(ROOT / "configs/openshell-praxis"))

    def test_operational_documents_exist(self):
        self.assertTrue((ROOT / "docs/examples/README.md").is_file())
        self.assertTrue((ROOT / "docs/examples/opencode-pr-queue/README.md").is_file())
        self.assertTrue((ROOT / "docs/examples/opencode-pr-queue/demo-task.md").is_file())
        self.assertTrue((ROOT / "openshell/harnesses/opencode/pr-queue/instructions.md").is_file())
        self.assertTrue((ROOT / "openshell/harnesses/opencode/pr-queue/lib.sh").is_file())
        guide = (ROOT / "docs/examples/opencode-pr-queue/README.md").read_text()
        self.assertIn("--capacity 10000000 --apply", guide)
        self.assertIn("sudo scripts/common/quota-reset --provider openai --apply", guide)
        self.assertIn("cached", guide)
        self.assertIn("openshell/harnesses/opencode/pr-queue/queue.sh", guide)
        self.assertIn("openshell/harnesses/opencode/pr-queue/collect.sh", guide)
        self.assertIn(
            "--config /usr/share/secure-single-server/configs/openshell-praxis",
            guide)
        self.assertIn("sudo tee /var/tmp/opencode-pr-queue-demo-task.md", guide)
        self.assertIn("--prompt-file /var/tmp/opencode-pr-queue-demo-task.md", guide)
        self.assertIn(
            'os_run "$repo/openshell/harnesses/opencode/pr-queue/queue.sh"',
            guide)
        self.assertIn(
            '--prompt-file "$repo/docs/examples/opencode-pr-queue/demo-task.md"',
            guide)


if __name__ == "__main__":
    unittest.main()
