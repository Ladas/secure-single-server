#!/usr/bin/env python3
"""Enable/disable one provider in an existing memory/Valkey gateway."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import signal
import subprocess
import sys
import tempfile
import time
import uuid

from provider_config import SingleValueAction, render, validate_vllm_endpoint
import quota_config

ROOT = Path(__file__).resolve().parents[2]
CONFIG = Path(os.environ.get("PRAXIS_CONFIG_DIR", "/etc/praxis"))


def create_cloud_secret(provider, version, *, reader=getpass.getpass, execute=subprocess.run):
    """Reuse the stdin-only secret helper; never pass a credential in argv."""
    value = reader(provider.capitalize() + " API key: ")
    if not value or any(character.isspace() for character in value):
        raise ValueError("API key must be nonempty and contain no whitespace")
    execute([str(ROOT / "scripts/common/secret-set"), provider, version],
            input=value, text=True, check=True)


def updated_config(template, installed, previous, selected, *, legacy=False, overrides=None):
    """Never reset settings from a different checkout during a provider change."""
    def configured(state):
        return quota_config.apply(render(template, vllm=state["vllm"], openai=bool(state["openai_secret"]),
                      anthropic=bool(state["anthropic_secret"]),
                      vllm_endpoint=state.get("vllm_endpoint", "")), overrides or {})

    expected = quota_config.apply(template, overrides or {}) if legacy else configured(previous)
    if installed != expected:
        raise ValueError("installed settings differ from these templates; use the matching checkout before changing providers")
    return None if previous == selected else configured(selected)


def service(*args, **kwargs):
    return subprocess.run(["bash", "-c", 'source "$1"; shift; as_service "$@"', "providers",
                           str(ROOT / "scripts/common/lib.sh"), *args], check=True, **kwargs)


def restart():
    service("systemctl", "--user", "daemon-reload")
    service("systemctl", "--user", "restart", "praxis.service")
    for _ in range(90):
        status = service("podman", "inspect", "praxis-shared-gateway", "--format",
                         '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}',
                         capture_output=True, text=True).stdout.strip()
        if status == "healthy":
            return
        time.sleep(1)
    raise RuntimeError("Praxis did not become healthy after configuration change")


def atomic_write(path, data, uid, gid, mode):
    fd, temp = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
            os.fchmod(output.fileno(), mode)
            os.fchown(output.fileno(), uid, gid)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def transaction(changes, manifest, gid, activate=restart, relabel=None, label="providers"):
    """Retain a recovery copy; restore files and the old service on any failure."""
    import stat
    paths = [*changes, manifest]
    previous = {p: (p.read_bytes(), p.stat()) if p.exists() else None for p in paths}
    recovery = manifest.parent / "rollback" / (label + "-" + str(time.time_ns()))
    recovery.mkdir(mode=0o700, parents=True)
    (recovery.parent).chmod(0o700)
    for index, (path, entry) in enumerate(previous.items()):
        if entry:
            backup = recovery / str(index)
            backup.write_bytes(entry[0])
            backup.chmod(0o600)
    (recovery / "paths.json").write_text(json.dumps([str(p) for p in paths], indent=2))
    print("Rollback files: " + str(recovery), flush=True)
    try:
        for path, data in changes.items():
            atomic_write(path, data, os.geteuid(), gid, 0o640)
        if relabel:
            relabel()
        activate()
        records = dict(line.split("  ", 1)[::-1] for line in previous[manifest][0].decode().splitlines())
        records.update({str(p): hashlib.sha256(data).hexdigest() for p, data in changes.items()})
        content = "".join(digest + "  " + path + "\n" for path, digest in records.items()).encode()
        atomic_write(manifest, content, os.geteuid(), gid, 0o640)
    except BaseException:
        for path, entry in previous.items():
            if entry:
                data, info = entry
                atomic_write(path, data, info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode))
            else:
                path.unlink(missing_ok=True)
        if relabel:
            relabel()
        try:
            activate()
        except Exception as error:
            raise RuntimeError("Files restored but previous service failed to recover; inspect " + str(recovery)) from error
        raise


def main():
    def interrupted(signum, frame):
        raise InterruptedError("provider change interrupted; restoring previous configuration")

    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("show", "enable", "disable"))
    parser.add_argument("provider", nargs="?", choices=("vllm", "openai", "anthropic"))
    parser.add_argument("--secret", help="use an existing secret NAME; omit to enter a new cloud key at a hidden prompt")
    parser.add_argument("--vllm-endpoint",
                        help="enable the separate-server route with RFC1918_IP:PORT; omit for deprecated co-located mode",
                        action=SingleValueAction)
    args = parser.parse_args()
    if args.action != "show" and not args.provider:
        parser.error("enable/disable requires a provider")
    if args.secret and (args.action != "enable" or args.provider == "vllm"):
        parser.error("--secret applies only when enabling OpenAI/Anthropic")
    if args.secret and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.secret):
        parser.error("invalid secret name")
    if args.vllm_endpoint is not None and (args.action != "enable" or args.provider != "vllm"):
        parser.error("--vllm-endpoint applies only when enabling vllm")
    if args.vllm_endpoint is not None:
        if not args.vllm_endpoint:
            parser.error("vllm endpoint must be RFC1918_IP:PORT")
        try:
            validate_vllm_endpoint(args.vllm_endpoint)
        except ValueError as error:
            parser.error(str(error))
    account = pwd.getpwnam(os.environ.get("PRAXIS_SERVICE_USER", "praxis-svc"))
    profile = (CONFIG / "shared-gateway.profile").read_text().strip()
    scenario = (CONFIG / "gateway.scenario").read_text().strip()
    if profile not in ("memory", "valkey") or scenario not in ("all-in-one", "remote-gateway"):
        parser.error("optional providers require all-in-one/remote-gateway with memory/valkey")
    unit_path = Path(f"/etc/containers/systemd/users/{account.pw_uid}/praxis.container")
    unit = unit_path.read_text()
    state = {"vllm": False, "vllm_endpoint": "", "openai_secret": "", "anthropic_secret": ""}
    for provider in ("openai", "anthropic"):
        matches = re.findall(r"^Secret=([^,\n]+),type=env,target=" + provider.upper() + r"_API_KEY$", unit, re.M)
        if matches:
            state[provider + "_secret"] = matches[0]
    state_file = CONFIG / "providers.json"
    if state_file.exists():
        stored = json.loads(state_file.read_text())
        legacy_state = set(state) - {"vllm_endpoint"}
        if set(stored) not in (set(state), legacy_state) or any(
                stored[p] != state[p] for p in ("openai_secret", "anthropic_secret")):
            raise ValueError("provider state differs from the installed secret references")
        stored.setdefault("vllm_endpoint", "")
        state = stored
    if args.action == "show":
        print(json.dumps(state, indent=2))
        return
    previous = state.copy()
    version = None
    if args.provider == "vllm":
        state["vllm"] = args.action == "enable"
        state["vllm_endpoint"] = args.vllm_endpoint or "" if args.action == "enable" else ""
    else:
        if args.action == "enable":
            if not args.secret:
                if not sys.stdin.isatty():
                    parser.error("new cloud keys require an interactive terminal; use --secret NAME for an existing secret")
                version = "manual-" + uuid.uuid4().hex[:12]
                args.secret = f"praxis-{args.provider}-api-key-{version}"
            else:
                service("podman", "secret", "inspect", args.secret, stdout=subprocess.DEVNULL)
        state[args.provider + "_secret"] = args.secret if args.action == "enable" else ""
    import yaml
    template = ROOT / ("configs/remote-gateway/gateway.yaml" if scenario == "remote-gateway" else
                       "configs/all-in-one/shared-gateway" + ("-valkey" if profile == "valkey" else "") + ".yaml")
    config = yaml.safe_load(template.read_text())
    if scenario == "remote-gateway" and profile == "valkey":
        for f in config["filter_chains"][0]["filters"]:
            if f["filter"] == "token_rate_limit":
                provider = f["rules"][0]["name"].split("-")[0]
                f["backend"] = {"kind": "valkey", "url": "${TOKEN_RATE_LIMIT_VALKEY_URL}",
                                "namespace": "secure-single-server:limits:" + provider}
    config = updated_config(config, yaml.safe_load((CONFIG / "shared-gateway.yaml").read_text()),
                            previous, state, legacy=not state_file.exists(),
                            overrides=quota_config.load(CONFIG / "quota-overrides.json"))
    if config is None:
        print("Provider configuration is unchanged.")
        return
    if version:
        create_cloud_secret(args.provider, version)
    lines = [line for line in unit.splitlines() if not re.match(
        r"Secret=.*target=(OPENAI|ANTHROPIC)_API_KEY$", line)]
    insertion = lines.index("[Container]") + 1
    for provider in ("openai", "anthropic"):
        if state[provider + "_secret"]:
            lines.insert(insertion, f"Secret={state[provider + '_secret']},type=env,target={provider.upper()}_API_KEY")
    changes = {CONFIG / "shared-gateway.yaml": (json.dumps(config, indent=2) + "\n").encode(),
               unit_path: ("\n".join(lines) + "\n").encode(),
               state_file: (json.dumps(state, indent=2) + "\n").encode()}
    transaction(changes, CONFIG / "shared-gateway.manifest", account.pw_gid,
                relabel=lambda: subprocess.run(["restorecon", "-F", str(CONFIG / "shared-gateway.yaml")], check=True))
    print("Provider change applied; TLS/JWT files, other secrets and Valkey data retained.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"error: {error}") from None
