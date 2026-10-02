#!/usr/bin/env python3
"""List or preview token capacities; add --apply to save and restart Praxis."""
import argparse
import json
import os
from pathlib import Path
import pwd
import shlex
import signal
import subprocess

import quota_config
from provider_manage import transaction

PROVIDERS = ("vllm", "openai", "anthropic")


def listing(config, *, provider=None, names=None):
    available = quota_config.rules(config)
    unknown = set(names or []) - set(available)
    if unknown:
        raise ValueError("unknown or disabled quota rules: " + ", ".join(sorted(unknown)))
    providers_available = list(PROVIDERS) + sorted({n.rsplit('-', 3)[0] for n in available
        if n.endswith(('-openai-rolling-day', '-anthropic-rolling-day'))
        and not n.startswith(tuple(p + '-' for p in PROVIDERS))})
    rows, seen = [], set()
    for chain in config["filter_chains"]:
        for item in chain["filters"]:
            if item["filter"] != "token_rate_limit":
                continue
            for rule in item["rules"]:
                name = rule["name"]
                if name in seen:
                    continue
                seen.add(name)
                owner = next((p for p in sorted(providers_available, key=len, reverse=True) if name.startswith(p + "-")), None)
                if (provider and owner != provider) or (names and name not in names):
                    continue
                minimum, reason = None, ""
                try:
                    minimum = quota_config.minimum_capacity(rule)
                except ValueError as error:
                    reason = str(error)
                rows.append({"provider": owner, "rule": name, "backend": item.get("backend", {}).get("kind", "memory"),
                             "window": rule.get("window", "-"), "capacity": rule["capacity"],
                             "minimum_capacity": minimum, "settable": not reason, "reason": reason})
    providers = []
    for name in providers_available:
        if provider and name != provider:
            continue
        matches = [row for row in rows if row["provider"] == name]
        # Availability is based on all installed rules, even for an exact-rule view.
        providers.append({"provider": name, "enabled": any(r.startswith(name + "-") for r in available),
                          "rules": len(matches), "settable": sum(row["settable"] for row in matches)})
    return {"providers": providers, "rules": rows}


def setting_commands(report):
    return ["sudo scripts/common/quota-set --rule " + shlex.quote(row["rule"]) +
            " --capacity " + str(row["capacity"]) for row in report["rules"] if row["settable"]]


def format_listing(report):
    lines = [f"{'Provider':<12} {'State':<10} {'Rules':>5} {'Settable':>9}"]
    for row in report["providers"]:
        state = "enabled" if row["enabled"] else "disabled"
        lines.append(f"{row['provider']:<12} {state:<10} {row['rules']:>5} {row['settable']:>9}")
    lines += ["", f"{'Rule':<36} {'Backend':<8} {'Window':<7} {'Capacity':>14} {'Minimum':>12} {'Settable':>9}"]
    for row in report["rules"]:
        minimum = "-" if row["minimum_capacity"] is None else f"{row['minimum_capacity']:,}"
        lines.append(f"{row['rule']:<36} {row['backend']:<8} {row['window']:<7} "
                     f"{row['capacity']:>14,} {minimum:>12} {('yes' if row['settable'] else 'no'):>9}")
        if row["reason"]:
            lines.append("  " + row["rule"] + ": " + row["reason"])
    if not report["rules"]:
        lines.append("No enabled quota rules match this selection.")
    lines += ["", "Minimum = smallest capacity accepted with the existing reservation.",
              "Only enabled, settable rules can be adjusted. Use --provider NAME or --rule NAME."]
    commands = setting_commands(report)
    if commands:
        lines += ["", "Preview a change: replace the current capacity in the selected command:", *commands,
                  "To save the reviewed change, append --apply (restarts Praxis)."]
    lines += ["", "Check usage: sudo scripts/common/quota-status",
              "List testing reset commands: sudo scripts/common/quota-reset --list"]
    return "\n".join(lines)


def plan(config, overrides, value, *, provider=None, names=None):
    quota_config.capacity(value)
    available = quota_config.rules(config)
    selected = list(dict.fromkeys(names or []))
    if provider:
        selected = [row["rule"] for row in listing(config, provider=provider)["rules"]]
    if not selected:
        raise ValueError("no matching enabled quota rules; run quota-set --list first")
    unknown = set(selected) - set(available)
    if unknown:
        raise ValueError("unknown or disabled quota rules: " + ", ".join(sorted(unknown)))
    updated = {**overrides, **dict.fromkeys(selected, value)}
    quota_config.apply(config, updated)
    return updated, [(name, available[name]["capacity"], value) for name in selected]


def change(root, config, overrides, value, gid, *, provider=None, names=None, apply=False):
    updated, rows = plan(config, overrides, value, provider=provider, names=names)
    print(f"{'Rule':<36} {'Current':>14} {'Proposed':>14}")
    for name, old, new in rows:
        print(f"{name:<36} {old:>14,} {new:>14,}")
    if all(old == new for _, old, new in rows):
        print("Capacities are unchanged; no files written or services restarted.")
        return
    print("Applying restarts Praxis and interrupts active requests. Memory quotas and metrics reset; "
          "Valkey usage is retained. vLLM keeps running.", flush=True)
    if not apply:
        print("Preview only. Rerun with --apply to save these capacities.")
        return
    config_path = root / "shared-gateway.yaml"
    changes = {config_path: (json.dumps(quota_config.apply(config, updated), indent=2) + "\n").encode(),
               root / "quota-overrides.json": (json.dumps(updated, indent=2) + "\n").encode()}
    transaction(changes, root / "shared-gateway.manifest", gid, label="quotas",
                relabel=lambda: subprocess.run(["restorecon", "-F", str(config_path)], check=True))
    print("Capacities saved; Praxis is healthy. Provider settings and quota windows are unchanged.")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(prog="quota-set", description=__doc__)
    parser.add_argument("--list", action="store_true", help="list installed providers and settable rules without changing them")
    parser.add_argument("--json", action="store_true", help="emit structured output with --list")
    select = parser.add_mutually_exclusive_group()
    select.add_argument("--provider",
                        help="select all enabled quota rules for this provider")
    select.add_argument("--rule", action="append", help="select an exact rule name; repeat for multiple rules")
    parser.add_argument("--capacity", type=int, help="total tokens per existing rolling window")
    parser.add_argument("--apply", action="store_true", help="save capacities and restart Praxis (default: preview)")
    args = parser.parse_args(argv)
    if args.list:
        if args.capacity is not None or args.apply:
            parser.error("--list cannot be combined with --capacity or --apply")
    elif not (args.provider or args.rule) or args.capacity is None or args.json:
        parser.error("adjusting requires --provider/--rule and --capacity; --json requires --list")
    return args


def main():
    def interrupted(signum, frame):
        raise InterruptedError("quota change interrupted; restoring previous configuration")

    signal.signal(signal.SIGTERM, interrupted)
    args = parse_args()
    if os.geteuid() != 0:
        raise ValueError("run with sudo")
    root = Path(os.environ.get("PRAXIS_CONFIG_DIR", "/etc/praxis"))
    profile = (root / "shared-gateway.profile").read_text().strip()
    scenario = (root / "gateway.scenario").read_text().strip()
    if profile not in ("memory", "valkey") or scenario not in ("all-in-one", "remote-gateway"):
        raise ValueError("quota-set supports all-in-one/remote-gateway with memory/valkey")
    import yaml
    config = yaml.safe_load((root / "shared-gateway.yaml").read_text())
    if args.list:
        report = {"scenario": scenario, "profile": profile, **listing(config, provider=args.provider, names=args.rule)}
        print(json.dumps(report, indent=2) if args.json else
              f"Scenario: {scenario}; profile: {profile}\n\n" + format_listing(report))
        return
    account = pwd.getpwnam(os.environ.get("PRAXIS_SERVICE_USER", "praxis-svc"))
    change(root, config, quota_config.load(root / "quota-overrides.json"), args.capacity, account.pw_gid,
           provider=args.provider, names=args.rule, apply=args.apply)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"error: {error}") from None
