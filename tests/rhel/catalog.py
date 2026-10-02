#!/usr/bin/env python3
"""Validate the generated local catalog with the pinned Codex binary, without inference."""
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/common"))
from harness import write_codex_catalog


def check(model):
    with tempfile.TemporaryDirectory(prefix="praxis-catalog-") as directory:
        root = Path(directory)
        catalog = write_codex_catalog(model, root)
        env = {"PATH": os.environ["PATH"], "HOME": directory, "CODEX_HOME": directory,
               "PRAXIS_PLACEHOLDER_KEY": "local-placeholder"}
        command = ["codex", "-c", "model_catalog_json=" + json.dumps(str(catalog)),
                   "-c", 'model_provider="praxis"', "-c", 'model_providers.praxis.name="Praxis"',
                   "-c", 'model_providers.praxis.base_url="http://127.0.0.1:9/v1"',
                   "-c", 'model_providers.praxis.env_key="PRAXIS_PLACEHOLDER_KEY"',
                   "-c", 'model_providers.praxis.wire_api="responses"', "app-server"]
        with (root / "stderr").open("w+") as errors, subprocess.Popen(command, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=errors, text=True, env=env, cwd=directory) as process:
            try:
                with selectors.DefaultSelector() as reader:
                    reader.register(process.stdout, selectors.EVENT_READ)

                    def rpc(identifier, method, params):
                        process.stdin.write(json.dumps({"id": identifier, "method": method, "params": params}) + "\n")
                        process.stdin.flush()
                        deadline = time.monotonic() + 15
                        while time.monotonic() < deadline:
                            if not reader.select(timeout=1):
                                continue
                            line = process.stdout.readline()
                            if not line:
                                errors.seek(0)
                                raise AssertionError(errors.read()[-3000:])
                            response = json.loads(line)
                            if response.get("id") == identifier:
                                assert "error" not in response, response
                                return response["result"]
                        raise TimeoutError("Codex catalog probe timed out")

                    rpc(1, "initialize", {"clientInfo": {"name": "praxis-catalog-check", "version": "1.0.0"}})
                    entries = rpc(2, "model/list", {})["data"]
                    selected, = [entry for entry in entries if entry.get("model") == model]
                    assert not selected["hidden"] and selected["defaultReasoningEffort"] == "medium", selected
                    print(json.dumps({"status": "passed", "scope": "catalog parsing/listing only", "model": model}))
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("Run without Python -O")
    version = subprocess.check_output(["codex", "--version"], text=True).strip()
    expected = json.loads((ROOT / "configs/common/harness-versions.json").read_text())["@openai/codex"]
    if version != "codex-cli " + expected:
        raise SystemExit("Install the pinned Codex version before qualifying its catalog")
    for model in ("qwen3-8b", "qwen3.8-27b-int4"):
        check(model)
