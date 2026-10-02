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

from provider_config import SingleValueAction, render, validate_vllm_endpoint, custom_name, endpoint
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
                      vllm_endpoint=state.get("vllm_endpoint", ""),
                      shared_vllm=state.get("shared_vllm_quota", False), custom=state.get("custom_providers"),
                      models=state.get('models'),
                      hide_vllm_reasoning=state.get('hide_vllm_reasoning', False)), overrides or {})

    expected = quota_config.apply(template, overrides or {}) if legacy else configured(previous)
    if installed != expected and not legacy:
        # Older managed renderers omitted the Messages listener's model routes.
        # Accept exactly that predecessor; all other settings must still match.
        predecessor = json.loads(json.dumps(expected))
        for chain in predecessor['filter_chains']:
            if chain['name'] == 'anthropic':
                for item in chain['filters']:
                    if item['filter'] == 'router':
                        item['routes'] = [r for r in item['routes']
                                          if r.get('path') not in ('/vllm/v1/models', '/v1/models')]
        if installed == predecessor:
            expected = predecessor
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
    parser.add_argument("action", choices=("show", "enable", "disable", "unified", "models"))
    parser.add_argument("provider", nargs="?", help="vllm, openai, anthropic, or a custom provider name")
    parser.add_argument('--models', type=Path, help='JSON model catalog for unified (replaces native provider paths)')
    parser.add_argument('--vllm-reasoning', choices=('show', 'hide'),
                        help='unified only: show/hide vLLM Responses reasoning output; model thinking stays enabled')
    parser.add_argument('--openai-url', help='custom provider OpenAI-compatible HTTPS origin or /v1 URL')
    parser.add_argument('--anthropic-url', help='custom provider native Messages HTTPS origin')
    parser.add_argument("--shared-quota", action="store_true", help="enable vLLM with one Valkey allowance across both APIs")
    parser.add_argument("--capacity", type=int, help="capacity for --shared-quota (required for first migration)")
    parser.add_argument("--secret", help="use an existing secret NAME; omit to enter a new cloud key at a hidden prompt")
    parser.add_argument("--vllm-endpoint",
                        help="enable the separate-server route with RFC1918_IP:PORT; omit for deprecated co-located mode",
                        action=SingleValueAction)
    args = parser.parse_args()
    if args.action in ('enable', 'disable') and not args.provider:
        parser.error("enable/disable requires a provider")
    if args.action in ('unified', 'models', 'show') and args.provider:
        parser.error('this action takes no provider argument')
    if bool(args.models) != (args.action == 'unified'):
        parser.error('unified requires --models FILE; other actions do not accept --models')
    if args.vllm_reasoning and args.action != 'unified':
        parser.error('--vllm-reasoning applies only to unified')
    if args.shared_quota and (args.action != 'enable' or args.provider != 'vllm'):
        parser.error('--shared-quota applies to enable vllm')
    if args.capacity is not None and not args.shared_quota:
        parser.error('--capacity requires --shared-quota')
    if args.shared_quota and args.capacity is None:
        parser.error('--shared-quota requires an explicit --capacity')
    if args.secret and (args.action != "enable" or args.provider == "vllm"):
        parser.error("--secret applies only when enabling an upstream provider")
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
    custom = args.provider not in (None, 'vllm', 'openai', 'anthropic')
    if custom:
        custom_name(args.provider)
    if (args.openai_url or args.anthropic_url) and (not custom or args.action != 'enable'):
        parser.error('provider URLs apply only to enable CUSTOM_NAME')
    for url in (args.openai_url, args.anthropic_url):
        if url:
            endpoint(url)
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
        optional = {"shared_vllm_quota", "custom_providers", "models", "hide_vllm_reasoning"}
        if set(stored) - optional not in (set(state), legacy_state) or any(stored[p] != state[p] for p in ("openai_secret", "anthropic_secret")):
            raise ValueError("provider state differs from the installed secret references")
        stored.setdefault("vllm_endpoint", "")
        for slug, settings in stored.get('custom_providers', {}).items():
            custom_name(slug)
            target = 'CUSTOM_' + slug.upper().replace('-', '_') + '_API_KEY'
            expected = f"Secret={settings['secret']},type=env,target={target}"
            if expected not in unit.splitlines():
                raise ValueError('custom provider state differs from installed secret references')
        state = stored
    if args.action == "show":
        print(json.dumps(state, indent=2))
        return
    if args.action == 'models':
        import yaml
        from unified_config import active
        config = yaml.safe_load((CONFIG / 'shared-gateway.yaml').read_text())
        print(json.dumps({api: active(state.get('models', []), config, api)
                          for api in ('openai', 'anthropic')}, indent=2))
        return
    previous = json.loads(json.dumps(state))
    sharing = args.shared_quota and not state.get('shared_vllm_quota', False)
    if sharing and not previous['vllm']:
        parser.error('enable vllm first, then rerun with --shared-quota to preserve any retained API ledgers')
    if args.shared_quota:
        state['shared_vllm_quota'] = True

    version = None
    if args.action == 'unified':
        from unified_config import validate
        state['models'] = validate(json.loads(args.models.read_text()))
        if args.vllm_reasoning:
            state['hide_vllm_reasoning'] = args.vllm_reasoning == 'hide'
    elif args.provider == "vllm":
        state["vllm"] = args.action == "enable"
        # Changing the quota must not silently redirect a separate inference host
        # back to the co-located container. Explicit route changes still work.
        if not args.shared_quota or args.vllm_endpoint is not None:
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
        if custom:
            configured = state.setdefault('custom_providers', {})
            if args.action == 'disable':
                configured.pop(args.provider, None)
            else:
                item = configured.get(args.provider, {}).copy()
                item.update({api + '_url': value for api, value in
                             (('openai', args.openai_url), ('anthropic', args.anthropic_url)) if value})
                if not any(item.get(api + '_url') for api in ('openai', 'anthropic')):
                    parser.error('a new custom provider needs --openai-url and/or --anthropic-url')
                item['secret'] = args.secret
                configured[args.provider] = item
        else:
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
    installed = yaml.safe_load((CONFIG / "shared-gateway.yaml").read_text())
    overrides = quota_config.load(CONFIG / 'quota-overrides.json')
    config = updated_config(config, installed,
                            previous, state, legacy=not state_file.exists(),
                            overrides=overrides)
    if args.shared_quota:
        overrides['vllm-rolling-day'] = quota_config.capacity(args.capacity)
        config = quota_config.apply(config or installed, overrides)
    if config is None or (config == installed and state == previous):
        print("Provider configuration is unchanged.")
        return
    if version:
        if custom:
            value = getpass.getpass(args.provider + ' API key: ')
            if not value or any(c.isspace() for c in value):
                raise ValueError('API key must be nonempty and contain no whitespace')
            service('podman', 'secret', 'create', args.secret, '-', input=value, text=True,
                    stdout=subprocess.DEVNULL)
        else:
            create_cloud_secret(args.provider, version)
    lines = [line for line in unit.splitlines() if not re.match(
        r"Secret=.*target=(OPENAI|ANTHROPIC|CUSTOM_[A-Z0-9_]+)_API_KEY$", line)]
    insertion = lines.index("[Container]") + 1
    for provider in ("openai", "anthropic"):
        if state[provider + "_secret"]:
            lines.insert(insertion, f"Secret={state[provider + '_secret']},type=env,target={provider.upper()}_API_KEY")
    for slug, settings in state.get('custom_providers', {}).items():
        target = 'CUSTOM_' + slug.upper().replace('-', '_') + '_API_KEY'
        lines.insert(insertion, f"Secret={settings['secret']},type=env,target={target}")
    changes = {CONFIG / "shared-gateway.yaml": (json.dumps(config, indent=2) + "\n").encode(),
               unit_path: ("\n".join(lines) + "\n").encode(),
               state_file: (json.dumps(state, indent=2) + "\n").encode()}
    if args.shared_quota:
        changes[CONFIG / 'quota-overrides.json'] = (json.dumps(overrides, indent=2) + '\n').encode()
    migrate = None
    if sharing:
        from quota_share import prepare
        migrate = prepare(installed)
    try:
        if migrate:
            service('systemctl', '--user', 'stop', 'praxis.service')
            migrate()
        transaction(changes, CONFIG / "shared-gateway.manifest", account.pw_gid,
                    relabel=lambda: subprocess.run(["restorecon", "-F", str(CONFIG / "shared-gateway.yaml")], check=True))
    finally:
        if migrate:
            service('systemctl', '--user', 'start', 'praxis.service')
    print("Provider change applied; TLS/JWT files, other secrets and Valkey data retained.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"error: {error}") from None
