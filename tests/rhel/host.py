#!/usr/bin/env python3
"""Disposable RHEL host test driver. Invoked by run.py over SSH as root."""
import argparse
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
STATE = Path("/var/lib/praxis-rhel-smoke")
MOCK_IMAGE = "docker.io/library/python@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7"


def run(*args, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def capture(*args):
    return run(*args, stdout=subprocess.PIPE, text=True).stdout.strip()


def service(*args, **kwargs):
    return run("bash", "-c", 'source "$1"; shift; as_service "$@"', "service",
               ROOT / "scripts/common/lib.sh", *args, **kwargs)


def service_output(*args):
    return service(*args, stdout=subprocess.PIPE, text=True).stdout.strip()


def installed(args):
    if Path("/etc/praxis/gateway.scenario").read_text().strip() != args.scenario:
        raise ValueError("installed scenario differs from requested test scenario")
    if Path("/etc/praxis/shared-gateway.profile").read_text().strip() != args.profile:
        raise ValueError("installed profile differs; complete tests and explicitly switch the test-owned profile")
    service("true")
    run("scripts/common/verify", "--host")
    uid = pwd.getpwnam("praxis-svc").pw_uid
    unit = Path(f"/etc/containers/systemd/users/{uid}/praxis.container").read_text()
    secrets = {}
    for line in unit.splitlines():
        if line.startswith("Secret="):
            name = line.split("=", 1)[1].split(",", 1)[0]
            if "-smoke-" not in name:
                raise ValueError("only test-owned synthetic secrets may be used by this suite")
            target = line.rsplit("target=", 1)[1]
            secrets[target] = name
    return secrets


def invalidate_mock_results(profile):
    for kind in ("baseline", "providers"):
        (STATE / f"{kind}-{profile}.json").unlink(missing_ok=True)


def mock_secrets(args, mounted):
    state_path = STATE / "state.json"
    secrets = {}
    if state_path.exists():
        previous = json.loads(state_path.read_text())
        if not previous.get("mock"):
            raise ValueError("use --phase mock-again to replace a real-Qwen installation")
        if previous.get("scenario") != args.scenario or previous.get("profile") != args.profile:
            raise ValueError("mock state does not match the requested scenario/profile")
        secrets.update(previous["secrets"])
    secrets.update(mounted)
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        if "-smoke-" not in secrets.get(key, ""):
            raise ValueError(f"missing synthetic {key}; complete --phase install first")
        service("podman", "secret", "exists", secrets[key])
    return secrets


def mock_setup(args):
    import yaml
    secrets = mock_secrets(args, installed(args))
    STATE.mkdir(mode=0o700, exist_ok=True)
    invalidate_mock_results(args.profile)
    fixture = STATE / "bundle"
    for directory in ("configs", "scripts", "tests"):
        shutil.copytree(ROOT / directory, fixture / directory, dirs_exist_ok=True)
    for source in ("configs/all-in-one/shared-gateway.yaml", "configs/all-in-one/shared-gateway-valkey.yaml",
                   "configs/remote-gateway/gateway.yaml"):
        path = fixture / source
        config = yaml.safe_load(path.read_text())
        for chain in config["filter_chains"]:
            for item in chain["filters"]:
                if item["filter"] == "load_balancer":
                    for cluster in item["clusters"]:
                        port = 18080 if cluster["name"] == "openai" else 18081
                        cluster["endpoints"] = [f"praxis-rhel-mock:{port}"]
                        cluster.pop("http", None)
                        cluster.pop("tls", None)
        config["insecure_options"] = {"allow_private_endpoints": True, "allow_private_upstreams": True}
        class IndentedDumper(yaml.SafeDumper):
            def increase_indent(self, flow=False, indentless=False):
                return super().increase_indent(flow, False)
        path.write_text(yaml.dump(config, Dumper=IndentedDumper, sort_keys=False))
    # The mock has no host ports. Its control listener is container-loopback only.
    mock_files = Path("/etc/praxis-rhel-smoke")
    account = pwd.getpwnam("praxis-svc")
    for directory in (mock_files, mock_files / "common", mock_files / "rhel"):
        directory.mkdir(mode=0o750, exist_ok=True)
        os.chown(directory, 0, account.pw_gid)
    for src, dst in ((ROOT / "tests/common/provider.py", mock_files / "common/provider.py"),
                     (ROOT / "tests/rhel/harness_provider.py", mock_files / "rhel/harness_provider.py")):
        shutil.copyfile(src, dst)
        os.chown(dst, 0, account.pw_gid)
        dst.chmod(0o640)
    label = capture("semanage", "fcontext", "-l", "-C")
    run("semanage", "fcontext", "-m" if "/etc/praxis-rhel-smoke(/.*)?" in label else "-a",
        "-t", "container_file_t", "/etc/praxis-rhel-smoke(/.*)?")
    run("restorecon", "-R", str(mock_files))
    service("podman", "pull", MOCK_IMAGE)
    units = Path(f"/etc/containers/systemd/users/{account.pw_uid}")
    mock_unit = units / "praxis-rhel-mock.container"
    if mock_unit.exists():
        if "# Owned by tests/rhel/run.py" not in mock_unit.read_text():
            raise ValueError("refusing to replace an unrelated mock unit")
        service("systemctl", "--user", "stop", "praxis-rhel-mock.service")
    existing = subprocess.run(["bash", "-c", 'source "$1"; as_service podman container exists praxis-rhel-mock',
                               "exists", str(ROOT / "scripts/common/lib.sh")], check=False)
    if existing.returncode == 0:
        owner = service_output("podman", "inspect", "praxis-rhel-mock", "--format", '{{index .Config.Labels "rhel-smoke"}}')
        if owner != "true":
            raise ValueError("mock container name is already used by an unrelated container")
        service("podman", "rm", "--force", "--time", "1", "praxis-rhel-mock")
    mock_unit.write_text(f'''# Owned by tests/rhel/run.py; synthetic providers only.
[Unit]
Description=Private RHEL smoke provider
[Container]
Image={MOCK_IMAGE}
Pull=never
ContainerName=praxis-rhel-mock
Label=rhel-smoke=true
Network=praxis-private
NetworkAlias=praxis-rhel-mock
NetworkAlias=praxis-vllm
UserNS=keep-id:uid=1001,gid=1001
User=1001
Group=1001
ReadOnly=true
NoNewPrivileges=true
DropCapability=all
Environment=PYTHONDONTWRITEBYTECODE=1
Volume={mock_files}:/fixture:ro
Exec=python3 /fixture/rhel/harness_provider.py
[Service]
Restart=on-failure
TimeoutStopSec=5
[Install]
WantedBy=default.target
''')
    mock_unit.chmod(0o644)
    service("systemctl", "--user", "daemon-reload")
    service("systemctl", "--user", "start", "praxis-rhel-mock.service")
    command = [str(fixture / f"scripts/{args.scenario}/install"), "--profile", args.profile, "--replace", "--vllm",
               "--openai-secret", secrets["OPENAI_API_KEY"], "--anthropic-secret", secrets["ANTHROPIC_API_KEY"]]
    if args.scenario == "remote-gateway":
        command += ["--tls-cert", str(ROOT / "material/tls.pem"), "--tls-key", str(ROOT / "material/tls-key.pem"),
                    "--jwt-public-key", str(ROOT / "material/jwt-public.pem")]
    if args.profile == "valkey":
        valkey_unit = Path(f"/etc/containers/systemd/users/{account.pw_uid}/praxis-valkey.container").read_text()
        acl = next(line.split("=", 1)[1].split(",", 1)[0] for line in valkey_unit.splitlines() if line.startswith("Secret="))
        command += ["--valkey-image", "docker.io/valkey/valkey@sha256:63346cb24a61221e76bdf41acce99b3968a9fa83d8122144deab45394b27b4f2",
                    "--valkey-url-secret", secrets["TOKEN_RATE_LIMIT_VALKEY_URL"], "--valkey-acl-secret", acl]
    run(*command)
    run("scripts/common/verify", "--host")
    (STATE / "state.json").write_text(json.dumps({"scenario": args.scenario, "profile": args.profile,
        "mock": True, "hostname": args.hostname, "secrets": secrets}) + "\n")
    print("PASS: installed Praxis now routes exclusively to private synthetic LLM providers", flush=True)


def switch_profile(args):
    state_file = STATE / "state.json"
    previous = json.loads(state_file.read_text())
    if previous.get("scenario") != args.scenario or not previous.get("mock"):
        raise ValueError("profile switching requires this suite's existing synthetic scenario")
    if previous.get("profile") == args.profile:
        raise ValueError("profile is unchanged; use --phase all to rerun it")
    installed(argparse.Namespace(scenario=args.scenario, profile=previous["profile"]))
    service("systemctl", "--user", "stop", "praxis-rhel-mock.service")
    run("scripts/common/uninstall")  # Deliberately retains all secrets and quota data.
    state_file.rename(STATE / f"state-{previous['profile']}-{time.time_ns()}.json")


def provider_smoke(args):
    from integration import InstalledGateway, harnesses
    (STATE / f"providers-{args.profile}.json").unlink(missing_ok=True)
    secrets = installed(args)
    manager = STATE / "bundle/scripts/common/providers"
    protected = {p: p.read_bytes() for name in ("tls.pem", "tls-key.pem", "jwt-public.pem", "policy.yaml")
                 if (p := Path("/etc/praxis") / name).exists()}
    run(manager, "disable", "openai")
    run(manager, "disable", "anthropic")
    qwen = InstalledGateway(argparse.Namespace(**vars(args), provider="vllm"))
    cloud = InstalledGateway(args)
    qwen.contracts()
    for path in ("/v1/responses", "/v1/messages"):
        assert cloud.request(path)[0] == 404, "disabled cloud provider accepted a request"
    harnesses(qwen)
    run(manager, "enable", "openai", "--secret", secrets["OPENAI_API_KEY"])
    assert cloud.request("/v1/responses", {"model": "fixture", "input": "hello"})[0] == 200
    assert cloud.request("/v1/messages")[0] == 404
    qwen.contracts()
    run(manager, "enable", "anthropic", "--secret", secrets["ANTHROPIC_API_KEY"])
    cloud.contracts()
    qwen.contracts()
    harnesses(cloud, install=False)
    cloud.provider = "anthropic"
    harnesses(cloud, install=False, selected="opencode")
    cloud.provider = "cloud"
    before = len(cloud.control()["records"])
    assert qwen.request("/v1/chat/completions", {"model": "unknown", "messages": []})[0] == 404
    assert len(cloud.control()["records"]) == before, "unknown Qwen model fell back to cloud"
    qwen.control("http500", reset=True)
    assert qwen.request("/v1/responses", {"model": "qwen3-8b", "input": "hello"})[0] == 500
    assert len(cloud.control()["records"]) == before, "Qwen failure fell back to cloud"
    qwen.control("ok", reset=True)
    assert all(p.read_bytes() == data for p, data in protected.items()), "provider addition changed TLS/JWT identity"
    run("scripts/common/verify", "--host")
    (STATE / f"providers-{args.profile}.json").write_text(json.dumps({"scenario": args.scenario,
        "profile": args.profile, "completed": time.time(), "providers": ["vllm", "openai", "anthropic"]}) + "\n")
    print("PASS: Qwen-only → add OpenAI → add Anthropic; all native harnesses; no cloud fallback", flush=True)


def restore_production(args, secrets, account, config=Path("/etc/praxis")):
    # Installed TLS keys are service-readable (0640); installer inputs must
    # be private (0600). Copy the same identity without altering managed files.
    with tempfile.TemporaryDirectory(prefix="real-config-", dir=STATE) as directory:
        material = Path(directory)
        if args.scenario == "remote-gateway":
            for name in ("tls.pem", "tls-key.pem", "jwt-public.pem"):
                destination = material / name
                shutil.copyfile(config / name, destination)
                destination.chmod(0o600)
        command = [ROOT / f"scripts/{args.scenario}/install", "--replace", "--vllm", "--profile", args.profile]
        if args.scenario == "remote-gateway":
            command += ["--tls-cert", str(material / "tls.pem"), "--tls-key", str(material / "tls-key.pem"),
                        "--jwt-public-key", str(material / "jwt-public.pem")]
        if args.profile == "valkey":
            valkey_unit = Path(f"/etc/containers/systemd/users/{account.pw_uid}/praxis-valkey.container").read_text()
            acl = next(line.split("=", 1)[1].split(",", 1)[0] for line in valkey_unit.splitlines() if line.startswith("Secret="))
            command += ["--valkey-image", "docker.io/valkey/valkey@sha256:63346cb24a61221e76bdf41acce99b3968a9fa83d8122144deab45394b27b4f2",
                        "--valkey-url-secret", secrets["TOKEN_RATE_LIMIT_VALKEY_URL"], "--valkey-acl-secret", acl]
        run(*command)


def real_setup(args):
    state_path = STATE / "state.json"
    previous = json.loads(state_path.read_text())
    if previous.get("scenario") != args.scenario or previous.get("profile") != args.profile:
        raise ValueError("real transition requires this suite's matching VM/profile")
    marker = STATE / f"providers-{args.profile}.json"
    if not marker.is_file():
        raise ValueError("run the complete mocked provider suite before real inference")
    passed = json.loads(marker.read_text())
    if passed.get("scenario") != args.scenario or passed.get("profile") != args.profile:
        raise ValueError("mock results do not match this scenario/profile")
    secrets = installed(args)
    # Only synthetic cloud secrets can be present; never remove a real credential.
    account = pwd.getpwnam("praxis-svc")
    if previous.get("mock"):
        # Restore production templates explicitly, in one installer operation.
        # Provider updates deliberately refuse a different template baseline.
        restore_production(args, secrets, account)
    unit = Path(f"/etc/containers/systemd/users/{account.pw_uid}/praxis-rhel-mock.container")
    if unit.exists():
        if "# Owned by tests/rhel/run.py" not in unit.read_text():
            raise ValueError("refusing to remove an unrelated mock unit")
        service("systemctl", "--user", "stop", "praxis-rhel-mock.service")
        unit.unlink()
        service("systemctl", "--user", "daemon-reload")
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        if key in secrets:
            service("podman", "secret", "rm", secrets[key])
    mock_files = Path("/etc/praxis-rhel-smoke")
    if mock_files.exists():
        shutil.rmtree(mock_files)
        run("semanage", "fcontext", "-d", "/etc/praxis-rhel-smoke(/.*)?")
    fixture = STATE / "bundle"
    if fixture.exists():
        shutil.rmtree(fixture)
    previous.update(mock=False, ready=False, inference=args.inference, secrets={})
    state_path.write_text(json.dumps(previous) + "\n")
    run("scripts/vllm/install", *(["--image", args.vllm_image] if args.vllm_image else []), args.inference)
    assert not service_output("podman", "ps", "--filter", "label=rhel-smoke=true", "--format", "{{.Names}}")
    run("scripts/common/verify", "--host")
    previous["ready"] = True
    state_path.write_text(json.dumps(previous) + "\n")
    print("PASS: synthetic providers removed; only private real Qwen enabled", flush=True)


def return_to_mocks(args):
    previous = json.loads((STATE / "state.json").read_text())
    if previous.get("mock") or previous.get("scenario") != args.scenario or previous.get("profile") != args.profile:
        raise ValueError("mock-again requires this suite's matching real-Qwen installation")
    installed(args)  # Refuses real cloud secrets and changed managed files.
    service("systemctl", "--user", "stop", "praxis-vllm.service")
    run("scripts/common/uninstall")
    (STATE / "state.json").rename(STATE / f"state-real-{time.time_ns()}.json")


def openshell_inference(state):
    if state.get("mock", True):
        return ["OPENSHELL_MODEL_ID=fixture"]
    if not state.get("ready"):
        raise ValueError("complete real-setup before OpenShell inference")
    return ["OPENSHELL_MODEL_ID=qwen3-8b", "PRAXIS_API_PREFIX=/vllm"]


def openshell_names(owner_command):
    result = run(*owner_command, "openshell", "sandbox", "list", "--output", "json",
                 cwd="/", capture_output=True, text=True)
    return {item["name"] for item in json.loads(result.stdout)["sandboxes"]}


def openshell_leftovers(owner_command, existing, attempts=15):
    # Delete accepts the request before the gateway finishes removing containers.
    for attempt in range(attempts):
        leftovers = sorted(name for name in openshell_names(owner_command) - existing
                           if name.startswith(("ospx-smoke-", "policy-deny-", "policy-allow-")))
        if not leftovers or attempt + 1 == attempts:
            return leftovers
        time.sleep(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, choices=("all-in-one", "remote-gateway"))
    parser.add_argument("--profile", required=True, choices=("memory", "valkey"))
    parser.add_argument("--phase", required=True, choices=("install", "mock", "test", "check", "openshell", "switch-profile", "providers", "gpu-drivers", "real-setup", "real-test", "mock-again", "all"))
    parser.add_argument("--inference", choices=("cpu", "gpu"))
    parser.add_argument("--vllm-image")
    parser.add_argument("--harness", choices=("codex", "opencode", "claude"))
    parser.add_argument("--hostname", required=True)
    args = parser.parse_args()
    if args.vllm_image is not None and (args.phase != "real-setup" or not re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", args.vllm_image)):
        parser.error("--vllm-image requires real-setup and an immutable NAME@sha256:DIGEST")
    if os.geteuid() != 0:
        parser.error("run as root on the disposable test VM")
    os.chdir(ROOT)
    if args.phase == "mock-again":
        return_to_mocks(args)
        args.phase = "all"
    if args.phase == "gpu-drivers":
        run("scripts/vllm/prepare-gpu")
        return
    if args.phase == "real-setup":
        if not args.inference:
            parser.error("real-setup needs --inference cpu|gpu")
        real_setup(args)
        return
    if args.phase == "real-test":
        state = json.loads((STATE / "state.json").read_text())
        if state.get("scenario") != args.scenario or state.get("profile") != args.profile:
            raise ValueError("real test requires the matching installed scenario/profile")
        if state.get("mock", True) or not state.get("ready", True):
            raise ValueError("complete real-setup before claiming real inference")
        run("scripts/common/verify", "--host")
        # After a reboot, Praxis can be healthy before vLLM finishes loading weights.
        for _ in range(150):
            try:
                service("podman", "exec", "praxis-vllm", "python3", "-c",
                        'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/v1/models",timeout=3).read()',
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                break
            except subprocess.CalledProcessError:
                time.sleep(2)
        else:
            raise ValueError("real vLLM was not ready within five minutes")
        run("python3", "tests/rhel/integration.py", "--scenario", args.scenario,
            "--profile", args.profile, "--hostname", args.hostname, "--provider", "vllm", "--real",
            *(["--harness", args.harness] if args.harness else []))
        return
    if args.phase == "switch-profile":
        switch_profile(args)
        args.phase = "all"
    if args.phase in ("install", "all"):
        run("dnf", "install", "-y", "podman", "openssl", "policycoreutils-python-utils", "curl", "jq",
            "tar", "gzip", "python3", "python3-pyyaml", "tmux", "git")
        command = ["bash", "tests/rhel/install-smoke.sh", args.scenario, args.profile]
        if args.scenario == "remote-gateway":
            command += [str(ROOT / "material")]
        if (STATE / "state.json").exists():
            installed(args)
            print("Existing synthetic installation verified; resuming smoke workflow", flush=True)
        else:
            run(*command)
    if args.phase in ("mock", "all"):
        mock_setup(args)
    if args.phase == "providers":
        mock_setup(args)
        provider_smoke(args)
    if args.phase in ("test", "all"):
        run("python3", "tests/rhel/integration.py", "--scenario", args.scenario,
            "--profile", args.profile, "--hostname", args.hostname)
        if args.phase == "all":
            provider_smoke(args)
    if args.phase == "check":
        run("scripts/common/status")
        run("scripts/common/verify", "--host")
    if args.phase == "openshell":
        if args.scenario != "all-in-one" or not (STATE / f"baseline-{args.profile}.json").is_file():
            raise ValueError("OpenShell requires a passing all-in-one baseline on this VM first")
        installed(args)
        protected = {p: p.read_bytes() for p in Path("/etc/praxis").iterdir() if p.is_file()}
        run("scripts/openshell-praxis/install", "--owner", "openshell-svc")
        if any(p.read_bytes() != data for p, data in protected.items()):
            raise ValueError("OpenShell changed the Praxis baseline")
        print("PASS: OpenShell addon preserves installed all-in-one Praxis files", flush=True)
        owner = pwd.getpwnam("openshell-svc")
        # Registration belongs to the locked owner, as in openshell/tests/runtime.sh.
        # Copy public source only; never expose the private administrator bundle.
        with tempfile.TemporaryDirectory(prefix="praxis-openshell-smoke-", dir="/var/tmp") as directory:
            for name in ("configs", "scripts", "tests", "openshell"):
                shutil.copytree(ROOT / name, Path(directory) / name)
            run("chown", "-R", f"root:{owner.pw_gid}", directory)
            run("chmod", "-R", "u=rwX,g=rX,o=", directory)
            owner_command = ["runuser", "-u", "openshell-svc", "--", "env", "-i",
                f"HOME={owner.pw_dir}", "PATH=/usr/local/bin:/usr/bin:/usr/sbin:/bin", "LANG=C.UTF-8",
                f"XDG_RUNTIME_DIR=/run/user/{owner.pw_uid}",
                f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{owner.pw_uid}/bus",
                "OPENSHELL_TELEMETRY_ENABLED=false",
                *openshell_inference(json.loads((STATE / "state.json").read_text()))]
            existing = openshell_names(owner_command)
            result = subprocess.run([*owner_command, "bash", str(Path(directory) / "tests/openshell-praxis/smoke.sh")], cwd="/")
            if result.returncode:
                print("Integrated inference failed; checking independent policy positive control separately", flush=True)
                policy = subprocess.run([*owner_command, "bash", str(Path(directory) / "openshell/tests/openshell-policy.sh")], cwd="/")
                print(f"Independent policy suite exit code: {policy.returncode}", flush=True)
            leftovers = openshell_leftovers(owner_command, existing)
            print("OpenShell test sandbox leftovers: " + json.dumps(leftovers), flush=True)
            if result.returncode or leftovers:
                raise ValueError("OpenShell qualification failed; keep experimental support and retain the evidence")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"error: {error}") from None
