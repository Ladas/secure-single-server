#!/usr/bin/env python3
"""Validate all profiles with the pinned CLI in a network-disabled container.

The numeric-port control must pass parsing and reach a deliberately unavailable
gateway. The string-port control must fail schema decoding first. No sandbox
can be created, and no local OpenShell registration is read or changed.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/common"))
from evidence import save
sys.path.insert(0, str(ROOT / "openshell/tests"))
from schema import validate_profiles


def main():
    engine = os.environ.get("CONTAINER_ENGINE", "podman")
    values = dict(line.split("=", 1) for line in (ROOT / "openshell/configs/images.env").read_text().splitlines()
                  if line.startswith("ODH_"))
    image = json.loads(values["ODH_CLI_IMAGE"])
    available = subprocess.run([engine, "image", "inspect", image], capture_output=True, check=False)
    if available.returncode:
        subprocess.run([engine, "pull", image], check=True)
    result = {"status": "failed", "profiles": []}
    def invoke(target):
        return subprocess.run([engine, "run", "--rm", "--network", "none",
                "--read-only", "--cap-drop", "all", "--security-opt", "no-new-privileges",
                "--mount", f"type=bind,source={target},target=/policy.yaml,ro,Z", image,
                "policy", "set", "schema-only", "--policy", "/policy.yaml",
                "--gateway-endpoint", "http://127.0.0.1:9"], capture_output=True, text=True, timeout=20)
    try:
        validate_profiles(invoke, result["profiles"])
        result["status"] = "passed"
    finally:
        save("openshell-schema", result)
    return int(result["status"] != "passed")


if __name__ == "__main__":
    if not __debug__ or os.environ.get("PYTHONOPTIMIZE"):
        raise SystemExit("Run tests without Python -O/PYTHONOPTIMIZE")
    raise SystemExit(main())
