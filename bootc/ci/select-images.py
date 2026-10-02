#!/usr/bin/env python3
"""Select bootc image targets from changed paths."""

import fnmatch
import json
import sys


CI_PATHS = (
    ".github/workflows/bootc-images.yml",
    "bootc/build",
    "bootc/test-images",
    "bootc/ci/select-images.py",
)

BASE_PATHS = CI_PATHS + (
    "bootc/Containerfile",
    "bootc/scripts/admin",
    "bootc/scripts/common",
    "bootc/scripts/inference-check",
    "bootc/scripts/reconcile",
    "bootc/scripts/vllm",
    "bootc/scripts/vllm-common",
    "bootc/scripts/vllm-lib",
    "bootc/systemd/*",
    "configs/*",
    "openshell/configs/*",
    "openshell/scripts/*",
    "scripts/common/*",
)

PRAXIS_PATHS = CI_PATHS + (
    "bootc/Containerfile.praxis",
    "bootc/scripts/praxis",
    "bootc/systemd/secure-single-server-praxis.service",
    "bootc/systemd/delegate.conf",
    "scripts/common/lib.sh",
    "scripts/common/install",
    "scripts/common/secret-set",
    "configs/all-in-one/shared-gateway.yaml",
    "configs/common/quadlet/praxis.container.in",
    "configs/common/quadlet/praxis.network",
    "configs/vllm/praxis-remote.yaml",
    "configs/vllm/praxis.container.in",
)

VLLM_SHARED_PATHS = CI_PATHS + (
    "bootc/scripts/vllm-common",
    "bootc/scripts/vllm",
    "bootc/scripts/vllm-lib",
    "bootc/systemd/secure-single-server-vllm.service",
    "bootc/systemd/delegate.conf",
    "scripts/common/lib.sh",
    "scripts/common/install",
    "configs/vllm/images.env",
)

VLLM_CPU_PATHS = VLLM_SHARED_PATHS + (
    "bootc/Containerfile.vllm.cpu",
)

VLLM_GPU_PATHS = VLLM_SHARED_PATHS + (
    "bootc/Containerfile.vllm.gpu",
    "bootc/install-nvidia",
)

HARNESS_PATHS = BASE_PATHS + (
    "bootc/Containerfile.harness",
    "bootc/harnesses/*",
    "openshell/harnesses/*",
)


def matches(path, patterns):
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def main():
    changed = {line.strip() for line in sys.stdin if line.strip()}
    selected = {
        "praxis": any(matches(path, PRAXIS_PATHS) for path in changed),
        "vllm_cpu": any(matches(path, VLLM_CPU_PATHS) for path in changed),
        "vllm_gpu": any(matches(path, VLLM_GPU_PATHS) for path in changed),
        "harnesses": any(matches(path, HARNESS_PATHS) for path in changed),
    }
    json.dump(selected, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
