#!/usr/bin/env python3
"""Export public runtime evidence on the RHEL gateway; no private keys or config contents."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/rhel"))
from host import service_output, installed_model
from integration import runtime_metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="public HTTPS origin used by the separate client")
    args = parser.parse_args()
    parsed = urlsplit(args.url)
    if (os.geteuid() != 0 or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        parser.error("run as administrator on the gateway with its HTTPS origin")
    config = Path("/etc/praxis")
    if (config / "gateway.scenario").read_text().strip() != "remote-gateway":
        parser.error("external acceptance requires a remote-gateway installation")
    subprocess.run([str(ROOT / "scripts/common/verify"), "--host"], check=True, stdout=sys.stderr)
    mock = bool(service_output("podman", "ps", "--filter", "name=^praxis-rhel-mock$", "--format", "{{.Names}}"))
    backend = "praxis-rhel-mock" if mock else "praxis-vllm"
    unpublished = not service_output("podman", "port", backend)
    certificate = re.search(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
                            (config / "tls.pem").read_text(), re.S).group()
    result = {"scenario": "remote-gateway", "url": args.url.rstrip("/"), "collected_at": time.time(),
              "machine_id_sha256": hashlib.sha256(Path("/etc/machine-id").read_text().strip().encode()).hexdigest(),
              "profile": (config / "shared-gateway.profile").read_text().strip(), "mock": mock,
              "backend_ports_private": unpublished,
              "gateway_sha256": hashlib.sha256((config / "shared-gateway.yaml").read_bytes()).hexdigest(),
              "tls_leaf_sha256": hashlib.sha256(ssl.PEM_cert_to_DER_cert(certificate)).hexdigest(),
              "jwt_public_key": (config / "jwt-public.pem").read_text()}
    if mock:
        assert service_output("podman", "inspect", backend, "--format", '{{index .Config.Labels "rhel-smoke"}}') == "true"
        result.update(inference="mock", model="fixture or qwen3-8b; select the corresponding route")
    else:
        runtime = runtime_metadata()
        result.update(runtime=runtime, inference=runtime["inference"], model=installed_model(),
                      context_tokens=int(runtime["settings"]["--max-model-len"]))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    if not __debug__:
        raise SystemExit("Run without Python -O")
    main()
