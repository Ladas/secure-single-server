#!/usr/bin/env python3
"""Exercise the standalone Praxis dispatcher without a host deployment."""
import os
import shlex
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class PraxisDispatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.state = self.work / 'state'
        self.state.mkdir()
        self.script = self.make_script()
        self.env = {**os.environ, 'WORK': str(self.work)}

    def make_script(self):
        source = (ROOT / 'bootc/scripts/praxis').read_text()
        source = source.replace(
            'ROOT=/usr/share/secure-single-server',
            f'ROOT={shlex.quote(str(ROOT))}')
        source = source.replace(
            'source "${ROOT}/scripts/common/lib.sh"',
            '''source "${ROOT}/scripts/common/lib.sh"
require_root() { :; }
uname() { echo x86_64; }
secret_exists() { return 0; }
service_uid() { echo 1000; }
service_gid() { echo 1000; }
flock() { :; }
systemctl() { echo "SYSTEMCTL $*"; }
semanage() { :; }
restorecon() { :; }
install() {
  local args=()
  while (( "$#" )); do
    case "$1" in
      -o|-g) shift 2 ;;
      *) args+=("$1"); shift ;;
    esac
  done
  command install "${args[@]}"
}
render_template() {
  local source="$1" destination="$2"
  shift 2
  cp "${source}" "${destination}"
  while (( "$#" )); do
    local key="$1" value="$2"
    shift 2
    python3 - "${destination}" "${key}" "${value}" <<'PY'
from pathlib import Path
import sys

path, key, value = sys.argv[1:]
Path(path).write_text(Path(path).read_text().replace(f'@@{key}@@', value))
PY
  done
}
as_service() {
  if [[ "$1" == podman && "$2" == image && "$3" == exists ]]; then
    [[ -z "${IMAGE_EXISTS:-}" ]]
  elif [[ "$1" == podman && "$2" == pull ]]; then
    touch "$WORK/praxis-pull"
  elif [[ "$1" == podman && "$2" == image && "$3" == inspect ]]; then
    echo "${TEST_PLATFORM:-linux/amd64}"
  elif [[ "$1" == podman && "$2" == inspect ]]; then
    echo healthy
  else
    echo "SERVICE $*"
  fi
}''')
        source = source.replace(
            '"${ROOT}/scripts/common/install" --prepare', ':')
        source = source.replace(
            '/run/secure-single-server-praxis.lock',
            shlex.quote(str(self.work / 'secure-single-server-praxis.lock')))
        source = source.replace(
            '/etc/secure-single-server',
            shlex.quote(str(self.state)))
        source = source.replace(
            '/etc/praxis/shared-gateway.yaml',
            shlex.quote(str(self.work / 'praxis/shared-gateway.yaml')))
        source = source.replace(
            '/etc/containers/systemd/users',
            shlex.quote(str(self.work / 'containers/users')))
        script = self.work / 'dispatcher'
        script.write_text(source)
        script.chmod(0o755)
        return script

    def run_praxis(self, *args, env=None):
        return subprocess.run(
            ['bash', str(self.script), *args], env=env or self.env,
            capture_output=True, text=True, timeout=5)

    def test_inference_requires_a_subcommand(self):
        result = self.run_praxis('inference')
        self.assertEqual(result.returncode, 1)
        self.assertIn('expected inference cloud|remote-vllm', result.stderr)

    def test_inference_rejects_unknown_subcommand(self):
        result = self.run_praxis('inference', 'invalid')
        self.assertEqual(result.returncode, 1)
        self.assertIn('expected inference cloud|remote-vllm', result.stderr)

    def test_remote_vllm_requires_an_endpoint(self):
        result = self.run_praxis('inference', 'remote-vllm')
        self.assertEqual(result.returncode, 1)
        self.assertIn('expected inference cloud|remote-vllm', result.stderr)

    def test_activate_writes_secret_names_atomically(self):
        result = self.run_praxis(
            'activate', 'praxis-openai-api-key-v1', 'praxis-anthropic-api-key-v1')
        self.assertEqual(result.returncode, 0, result.stderr)
        names = self.state / 'secret-names'
        self.assertEqual(
            names.read_text(),
            'praxis-openai-api-key-v1 praxis-anthropic-api-key-v1\n')
        self.assertEqual(names.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.state.glob('.secret-names.*')), [])

    def prepare_reconcile(self):
        (self.work / 'praxis').mkdir()
        (self.work / 'containers/users/1000').mkdir(parents=True)

    def test_cloud_reconcile_renders_secret_names(self):
        self.prepare_reconcile()
        (self.state / 'inference-backend').write_text('cloud\n')
        (self.state / 'secret-names').write_text(
            'praxis-openai-api-key-v1 praxis-anthropic-api-key-v1')
        result = self.run_praxis('reconcile')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Praxis ready', result.stdout)
        config = self.work / 'praxis/shared-gateway.yaml'
        unit = self.work / 'containers/users/1000/praxis.container'
        self.assertIn('api.openai.com', config.read_text())
        self.assertIn('praxis-openai-api-key-v1', unit.read_text())
        self.assertIn('praxis-anthropic-api-key-v1', unit.read_text())
        self.assertNotIn('[Install]', unit.read_text())
        self.assertNotIn('WantedBy=default.target', unit.read_text())

    def test_remote_reconcile_renders_private_endpoint(self):
        self.prepare_reconcile()
        (self.state / 'inference-backend').write_text('remote-vllm\n')
        (self.state / 'vllm-endpoint').write_text('10.0.0.10:8000\n')
        result = self.run_praxis('reconcile')
        self.assertEqual(result.returncode, 0, result.stderr)
        config = self.work / 'praxis/shared-gateway.yaml'
        unit = self.work / 'containers/users/1000/praxis.container'
        self.assertIn('10.0.0.10:8000', config.read_text())
        self.assertNotIn('Secret=', unit.read_text())
        self.assertNotIn('[Install]', unit.read_text())
        self.assertNotIn('WantedBy=default.target', unit.read_text())

    def test_reconcile_pulls_missing_praxis_image(self):
        self.prepare_reconcile()
        (self.state / 'inference-backend').write_text('cloud\n')
        (self.state / 'secret-names').write_text(
            'praxis-openai-api-key-v1 praxis-anthropic-api-key-v1\n')
        result = self.run_praxis(
            'reconcile', env={**self.env, 'IMAGE_EXISTS': '1'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.work / 'praxis-pull').exists())

    def test_reconcile_rejects_wrong_praxis_platform(self):
        self.prepare_reconcile()
        (self.state / 'inference-backend').write_text('cloud\n')
        (self.state / 'secret-names').write_text(
            'praxis-openai-api-key-v1 praxis-anthropic-api-key-v1\n')
        result = self.run_praxis(
            'reconcile', env={**self.env, 'TEST_PLATFORM': 'linux/arm64'})
        self.assertEqual(result.returncode, 1)
        self.assertIn('unexpected image platform: linux/arm64', result.stderr)

    def test_reconcile_rejects_extra_secret_names(self):
        self.prepare_reconcile()
        (self.state / 'inference-backend').write_text('cloud\n')
        (self.state / 'secret-names').write_text('one two three\n')
        result = self.run_praxis('reconcile')
        self.assertEqual(result.returncode, 1)
        self.assertIn('expected exactly two secret names', result.stderr)
        self.assertFalse((self.work / 'praxis/shared-gateway.yaml').exists())


if __name__ == '__main__':
    unittest.main()
