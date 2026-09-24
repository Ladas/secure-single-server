#!/usr/bin/env python3
"""Exercise the copy/paste AWS workflow in Bash and zsh, without AWS access."""
import errno
import os
from pathlib import Path
import pty
import re
import select
import shutil
import subprocess
import tempfile
import termios
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
SHELLS = [path for name in ("bash", "zsh") if (path := shutil.which(name))]
SETUP = """
source scripts/aws/session.sh || { printf 'SOURCE_FAILED\\n'; return 1; }
REGION=eu-central-1 ARCH=amd64 SUBNET='' CLIENT_CIDR='' RUN_PREFIX=gateway-test
SSH_KEY=/test-private-location/key
AWS_TEST_CREDENTIALS=ready
AWS_ACCESS_KEY_ID=synthetic-access AWS_SECRET_ACCESS_KEY=synthetic-secret
aws() {
  case "$*" in
    *'get-caller-identity'*)
      [ "$MODE" != denied ] || return 23
      printf '%s\\n' '{"Account":"123456789012","Arn":"arn:aws:iam::123456789012:user/test"}' ;;
    *'describe-subnets'*)
      if [ "$MODE" = empty ]; then
        printf '%s\\n' '{"Subnets":[]}'
      else
        printf '%s\\n' '{"Subnets":[{"SubnetId":"subnet-b","AvailabilityZone":"zone-b","AvailableIpAddressCount":4},{"SubnetId":"subnet-full","AvailabilityZone":"zone-a","AvailableIpAddressCount":0},{"SubnetId":"subnet-a","AvailabilityZone":"zone-a","AvailableIpAddressCount":2}]}'
      fi ;;
    *) printf 'UNEXPECTED_AWS_CALL\\n'; return 99 ;;
  esac
}
curl() {
  [ "$MODE" != network_error ] || return 22
  if [ "$MODE" = invalid_ip ]; then printf 'invalid\\n'; else printf '192.0.2.7\\n'; fi
}
_aws_test_vm() {
  printf 'VM_CALL:%s\\n' "$1" >&2
  if [ "$MODE" = first_failed ]; then return 1; fi
  if [ "$1" = verify ]; then
    if [ "$MODE" = no_ip ]; then
      printf '%s\\n' '{"State":"pending","PublicIpAddress":null}'
    else
      printf '%s\\n' '{"State":"running","PublicIpAddress":"192.0.2.8"}'
    fi
  fi
}
"""


def environment():
    return {**{key: value for key, value in os.environ.items()
               if not key.startswith("AWS_") and key not in ("BASH_ENV", "ENV")},
            "HISTFILE": "/dev/null"}


def shell_args(shell):
    return [shell, "--noprofile", "--norc"] if Path(shell).name == "bash" else [shell, "-f"]


class SessionTest(unittest.TestCase):
    def run_shell(self, shell, script):
        result = subprocess.run(shell_args(shell) + ["-c", script], cwd=ROOT,
                                env=environment(), capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SHELL_ALIVE", result.stdout)
        self.assertNotIn("UNEXPECTED_AWS_CALL", result.stdout)
        return result.stdout + result.stderr

    def test_discovery_failure_never_exits_shell_or_leaves_ready_state(self):
        for shell in SHELLS:
            for mode in ("normal", "empty", "denied", "invalid_ip", "network_error"):
                with self.subTest(shell=shell, mode=mode):
                    output = self.run_shell(shell, "set -eu\nMODE=" + mode + "\n" + SETUP + """
AWS_TEST_READY=stale AWS_TEST_PLAN_INPUTS=stale ALL_IN_ONE_HOST=stale REMOTE_HOST=stale
if aws_test_discover; then printf 'DISCOVER_OK\\n'; else printf 'DISCOVER_FAILED\\n'; fi
printf 'READY:%s\\nPLAN:%s\\nHOST:%s\\nSHELL_ALIVE\\n' "${AWS_TEST_READY:-}" "${AWS_TEST_PLAN_INPUTS:-}" "${ALL_IN_ONE_HOST:-}"
""")
                    self.assertEqual("DISCOVER_OK" in output, mode == "normal")
                    self.assertIn("PLAN:\nHOST:\n", output)
                    if mode == "normal":
                        self.assertIn("subnet-a", output)
                        self.assertIn("192.0.2.7/32", output)
                    else:
                        self.assertIn("READY:\n", output)

    def test_failed_plan_and_changed_settings_block_apply(self):
        for shell in SHELLS:
            for mode in ("normal", "first_failed"):
                with self.subTest(shell=shell, mode=mode):
                    output = self.run_shell(shell, "set -eu\nMODE=" + mode + "\n" + SETUP + """
ACCOUNT=123456789012 SUBNET=subnet-a CLIENT_CIDR=192.0.2.7/32 AWS_TEST_READY=ready
if aws_test_plan; then printf 'PLAN_OK\\n'; else printf 'PLAN_FAILED\\n'; fi
REGION=eu-west-1
if aws_test_apply; then printf 'UNEXPECTED_APPLY\\n'; fi
printf 'SHELL_ALIVE\\n'
""")
                    self.assertNotIn("VM_CALL:apply", output)
                    self.assertNotIn("UNEXPECTED_APPLY", output)
                    self.assertEqual(output.count("VM_CALL:plan"), 2 if mode == "normal" else 1)

    def test_apply_stops_after_first_error_and_consumes_plan(self):
        for shell in SHELLS:
            with self.subTest(shell=shell):
                output = self.run_shell(shell, "set -eu\nMODE=normal\n" + SETUP + """
ACCOUNT=123456789012 SUBNET=subnet-a CLIENT_CIDR=192.0.2.7/32 AWS_TEST_READY=ready
if aws_test_plan; then printf 'PLAN_OK\\n'; fi
MODE=first_failed
if aws_test_apply; then printf 'UNEXPECTED_APPLY\\n'; fi
if aws_test_apply; then printf 'UNEXPECTED_RETRY\\n'; fi
printf 'SHELL_ALIVE\\n'
""")
                self.assertEqual(output.count("VM_CALL:apply"), 1)
                self.assertNotIn("UNEXPECTED_", output)

    def test_verify_failure_clears_previous_login_addresses(self):
        for shell in SHELLS:
            for mode in ("normal", "no_ip", "first_failed"):
                with self.subTest(shell=shell, mode=mode):
                    output = self.run_shell(shell, "set -eu\nMODE=" + mode + "\n" + SETUP + """
ACCOUNT=123456789012 ALL_IN_ONE_HOST=stale REMOTE_HOST=stale
if aws_test_verify; then printf 'VERIFY_OK\\n'; else printf 'VERIFY_FAILED\\n'; fi
printf 'HOST:%s\\nSHELL_ALIVE\\n' "${ALL_IN_ONE_HOST:-}"
""")
                    self.assertEqual("VERIFY_OK" in output, mode == "normal")
                    self.assertIn("HOST:ec2-user@192.0.2.8" if mode == "normal" else "HOST:\n", output)

    def test_key_overwrite_and_missing_settings_do_not_exit_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / "existing"
            key.write_text("preserve this file")
            for shell in SHELLS:
                with self.subTest(shell=shell):
                    output = self.run_shell(shell, "set -eu\nMODE=normal\n" + SETUP + f"""
SSH_KEY='{key}'
ssh-keygen() {{ printf 'UNEXPECTED_KEYGEN\\n'; }}
if aws_test_key; then printf 'UNEXPECTED_SUCCESS\\n'; fi
unset SSH_KEY
if aws_test_key; then printf 'UNEXPECTED_SUCCESS\\n'; fi
if aws_test_ssh all-in-one; then printf 'UNEXPECTED_SUCCESS\\n'; fi
printf 'SHELL_ALIVE\\n'
""")
                    self.assertNotIn("UNEXPECTED_", output)
                    self.assertEqual(key.read_text(), "preserve this file")

    def test_credential_prompts_on_a_real_terminal(self):
        for shell in SHELLS:
            for answers, loaded in (
                (("dummy-access", "dummy-secret", ""), True),
                (("dummy-access", "dummy-secret", "dummy-session"), True),
                (("",), False),
                (("dummy-access", ""), False),
                (("\x04",), False),
                (("dummy-access", "dummy-secret", "\x04"), False),
            ):
                with self.subTest(shell=shell, answers=len(answers)):
                    code = """
set -eu
if source scripts/aws/session.sh; then
  if aws_test_credentials; then printf 'CREDENTIALS_OK\\n'; else printf 'CREDENTIALS_FAILED\\n'; fi
fi
printf 'LOADED:%s\\nKEY:%s\\nSHELL_ALIVE\\n' "${AWS_TEST_CREDENTIALS:-}" "${AWS_ACCESS_KEY_ID:+present}"
"""
                    child, master = pty.fork()
                    if child == 0:
                        os.chdir(ROOT)
                        os.execve(shell, shell_args(shell) + ["-i", "-c", code], environment())
                    child_finished = False
                    transcript = b""
                    prompts = (b"AWS access key ID: ", b"AWS secret access key: ", b"AWS session token")
                    next_answer = 0
                    deadline = time.monotonic() + 8
                    try:
                        while time.monotonic() < deadline:
                            if select.select([master], [], [], 0.1)[0]:
                                try:
                                    chunk = os.read(master, 8192)
                                except OSError as error:
                                    if error.errno == errno.EIO:
                                        break
                                    raise
                                if not chunk:
                                    break
                                transcript += chunk
                            if (next_answer < len(answers) and prompts[next_answer] in transcript
                                    and not termios.tcgetattr(master)[3] & termios.ECHO):
                                answer = answers[next_answer]
                                os.write(master, (answer if answer == "\x04" else answer + "\n").encode())
                                next_answer += 1
                        finished, result = os.waitpid(child, os.WNOHANG)
                        while finished == 0 and time.monotonic() < deadline:
                            time.sleep(0.01)
                            finished, result = os.waitpid(child, os.WNOHANG)
                        child_finished = finished == child
                        self.assertTrue(child_finished, transcript.decode(errors="replace"))
                    finally:
                        if not child_finished:
                            os.kill(child, 9)
                            os.waitpid(child, 0)
                        os.close(master)
                    text = transcript.decode(errors="replace")
                    self.assertEqual(os.waitstatus_to_exitcode(result), 0, text)
                    self.assertIn("SHELL_ALIVE", text)
                    self.assertNotIn("dummy-access", text)
                    self.assertNotIn("dummy-secret", text)
                    self.assertNotIn("dummy-session", text)
                    if loaded:
                        self.assertIn("CREDENTIALS_OK", text)
                        self.assertIn("KEY:present", text)
                    else:
                        self.assertIn("CREDENTIALS_FAILED", text)
                        self.assertIn("KEY:\r\n", text)

    def test_guide_has_no_terminal_exiting_blocks(self):
        document = (ROOT / "docs/testing/aws.md").read_text()
        blocks = re.findall(r"^```console\n(.*?)^```", document, re.M | re.S)
        for block in blocks:
            self.assertNotRegex(block, r"\bexit\b|\bexec\b|\$\{[^}]*:\?|set -[a-zA-Z]*[eu]|read[^\n]* -p")
            for shell in SHELLS:
                result = subprocess.run(shell_args(shell) + ["-n"], input=block,
                                        capture_output=True, text=True, env=environment())
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_copyable_blocks_keep_shell_open_with_failed_commands(self):
        document = (ROOT / "docs/testing/aws.md").read_text()
        blocks = re.findall(r"^```console\n(.*?)^```", document, re.M | re.S)
        for shell in SHELLS:
            for block in blocks:
                with self.subTest(shell=shell, first_line=block.splitlines()[0]):
                    mocks = """
source() { return 1; }
aws_test_discover() { return 1; }
aws_test_key() { return 1; }
aws_test_plan() { return 1; }
aws_test_apply() { return 1; }
aws_test_verify() { return 1; }
aws_test_ssh() { return 1; }
"""
                    self.run_shell(shell, "set -eu\n" + mocks + block + "\nprintf 'SHELL_ALIVE\\n'\n")

    def test_other_guides_have_no_explicit_parent_shell_exit(self):
        for path in (ROOT / "docs").rglob("*.md"):
            blocks = re.findall(r"^```(?:console|sh|bash)\n(.*?)^```", path.read_text(), re.M | re.S)
            for block in blocks:
                self.assertNotRegex(block, r"\bexit\s+[0-9]|\$\{[^}]*:\?|set -[a-zA-Z]*[eu]", str(path))

    def test_bad_remote_user_url_keeps_terminal_open_and_clears_credentials(self):
        document = (ROOT / "docs/quickstarts/remote-gateway/users.md").read_text()
        blocks = re.findall(r"^```console\n(.*?)^```", document, re.M | re.S)
        validation = next(block for block in blocks if block.startswith('PRAXIS_URL="${PRAXIS_URL%/}"'))
        code = "set -eu\nPRAXIS_URL=http://invalid PRAXIS_CALLER_JWT=dummy PRAXIS_CA=''\n"
        output = self.run_shell(shutil.which("bash"), code + validation + """
printf 'URL:%s\\nJWT:%s\\nSHELL_ALIVE\\n' "${PRAXIS_URL:-}" "${PRAXIS_CALLER_JWT:-}"
""")
        self.assertIn("URL:\nJWT:\n", output)


if __name__ == "__main__":
    unittest.main()
