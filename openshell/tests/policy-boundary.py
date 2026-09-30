#!/usr/bin/env python3
"""Prove shipped OpenShell policies remain within reviewed access boundaries."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

import yaml


ROOT = Path(__file__).resolve().parents[2]
FAMILIES = {
    "codex": (ROOT / "openshell/harnesses/codex/profiles", "codex.yaml"),
    "openclaw": (ROOT / "openshell/harnesses/openclaw/profiles", "openclaw.yaml"),
    "opencode": (ROOT / "openshell/harnesses/opencode/profiles", "opencode.yaml"),
    "openshell-praxis": (ROOT / "configs/openshell-praxis/profiles", "openshell-praxis.yaml"),
    "vllm-harness": (ROOT / "configs/vllm/harness/profiles", "vllm-harness.yaml"),
}
REQUIRED_COVERAGE = {
    "filesystem",
    "network_l4",
    "network_rest",
    "process",
    "landlock",
}


def discover_policies():
    policies = set(ROOT.glob("openshell/harnesses/*/profiles/*/policy.yaml"))
    policies.update(ROOT.glob("configs/**/profiles/**/policy.yaml"))
    return sorted(policies)


def boundary_for(policy):
    for family, (directory, boundary_name) in FAMILIES.items():
        try:
            policy.relative_to(directory)
        except ValueError:
            continue
        return family, boundary_name
    raise AssertionError(f"shipped policy has no boundary family: {policy.relative_to(ROOT)}")


def render_policy(source, target):
    target.write_text(source.read_text().replace("@@PRAXIS_PORT@@", "18080"))


def run_prover(prover, candidate, boundary):
    completed = subprocess.run(
        [prover, "check", str(candidate), "--boundary", str(boundary),
         "--output", "json", "--timeout", "30s"],
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(
            f"policy prover did not return JSON: {completed.stdout} {completed.stderr}"
        ) from error
    return completed.returncode, result


def assert_coverage(result, context):
    domains = set(result.get("coverage", {}).get("domains", []))
    missing = REQUIRED_COVERAGE - domains
    assert not missing, f"{context} has incomplete prover coverage: missing {sorted(missing)}"
    print(f"PASS boundary: {context} (coverage: domains={','.join(sorted(domains))})")


def check_mutated_policy(prover, boundary, directory):
    source = ROOT / "openshell/harnesses/opencode/profiles/review/policy.yaml"
    policy = yaml.safe_load(source.read_text().replace("@@PRAXIS_PORT@@", "18080"))
    policy["network_policies"]["model_api"]["endpoints"].append(
        {
            "host": "example.invalid",
            "port": 443,
            "protocol": "rest",
            "access": "read-only",
            "enforcement": "enforce",
        }
    )
    candidate = directory / "mutated-policy.yaml"
    candidate.write_text(yaml.safe_dump(policy, sort_keys=False))
    returncode, result = run_prover(prover, candidate, boundary)
    assert returncode != 0, "mutated policy unexpectedly passed the boundary check"
    assert result["result"] == "exceeds_boundary", result
    assert result["counterexample"]["host"] == "example.invalid", result
    assert_coverage(result, "mutation control")


def main():
    prover = os.environ.get("OPENSHELL_PROVER_BIN", "openshell-prover")
    policies = discover_policies()
    assert len(policies) == 17, f"expected 17 shipped policies, found {len(policies)}"
    with tempfile.TemporaryDirectory() as temporary_directory:
        directory = Path(temporary_directory)
        boundaries = {}
        for index, source in enumerate(policies):
            family, boundary_name = boundary_for(source)
            boundary = directory / boundary_name
            if boundary_name not in boundaries:
                render_policy(ROOT / "tests/policy-boundary" / boundary_name, boundary)
                boundaries[boundary_name] = boundary
            candidate = directory / f"{family}-{index}.yaml"
            render_policy(source, candidate)
            returncode, result = run_prover(prover, candidate, boundary)
            context = source.relative_to(ROOT)
            assert returncode == 0, f"{context} exceeds or cannot be checked: {result}"
            assert result["result"] == "within_boundary", result
            assert_coverage(result, context)
        check_mutated_policy(prover, boundaries["opencode.yaml"], directory)
    print("openshell-policy-boundary: all shipped policies within boundaries OK")
    return 0


if __name__ == "__main__":
    if not __debug__ or os.environ.get("PYTHONOPTIMIZE"):
        raise SystemExit("Run tests without Python -O/PYTHONOPTIMIZE")
    raise SystemExit(main())
