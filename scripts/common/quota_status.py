#!/usr/bin/env python3
"""Read installed limits and private quota metrics without changing services."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

import yaml

LIB = Path(__file__).with_name("lib.sh")
PREFIX = "praxis_ai_token_rate_limit_"
# Praxis AI v0.4.1, token_rate_limit/backend.rs: v1 sliding-window ledger.
# https://github.com/praxis-proxy/ai/blob/b9d6016764888e02dc049ec088496b10b7e886c1/filters/src/token_rate_limit/backend.rs
LEDGER_IMAGE = "sha256:227d421e963c477038a884dc51ec880c5d0afa30098ae31028ecf85e963e40d5"
LEDGER_READ = """#!lua flags=no-writes
local now = redis.call('TIME')
local ms = tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000)
return {now[1], now[2],
  redis.call('ZRANGE', KEYS[1], '(' .. (ms - tonumber(ARGV[1])), '+inf', 'BYSCORE', 'WITHSCORES'),
  redis.call('HGETALL', KEYS[2])}
"""


def valkey_keys(namespace, rule):
    digest = hashlib.sha256("\0".join((namespace, rule, "__fallback__")).encode()).hexdigest()
    prefix = f"{namespace}:v1:{digest}"
    return [prefix + ":settled", prefix + ":active"]


def valkey_balance(snapshot, window_ms, timeout_ms):
    """Mirror admission's expiry accounting without expiring or changing any entry."""
    def integer(value):
        if not re.fullmatch(r"[0-9]+", str(value)):
            raise ValueError("unrecognized Valkey ledger number")
        return int(value)

    if not isinstance(snapshot, list) or len(snapshot) != 4:
        raise ValueError("unrecognized Valkey ledger snapshot")
    seconds, micros, settled, active = snapshot
    if not all(isinstance(values, list) and len(values) % 2 == 0 for values in (settled, active)):
        raise ValueError("unrecognized Valkey ledger entries")
    if integer(micros) >= 1000000:
        raise ValueError("invalid Valkey server timestamp")
    now = integer(seconds) * 1000 + integer(micros) // 1000
    settled_sum, held_sum = 0, 0
    for member, score in zip(settled[::2], settled[1::2]):
        match = re.fullmatch(r"(?:settled|expired):[0-9]+:([0-9]+)", str(member))
        at = integer(score)
        if not match or at > now:
            raise ValueError("unrecognized Valkey settlement")
        if at > now - window_ms:
            settled_sum += integer(match[1])
    for identifier, value in zip(active[::2], active[1::2]):
        integer(identifier)
        match = re.fullmatch(r"([0-9]+)\|([0-9]+)", str(value))
        if not match or integer(match[2]) > now:
            raise ValueError("unrecognized Valkey reservation")
        amount, at = integer(match[1]), integer(match[2])
        # Expiry retains the estimate at its reservation timestamp; it is not a refund.
        if now - at < timeout_ms or at > now - window_ms:
            held_sum += amount
    return {"sampled_at_ms": now, "settled_tokens": settled_sum,
            "held_tokens": held_sum, "charged": settled_sum + held_sum}


def read_valkey_balances(config, rows):
    selected = []
    by_name = {row["rule"]: row for row in rows}
    for chain in config["filter_chains"]:
        for item in chain["filters"]:
            backend = item.get("backend", {})
            if item["filter"] != "token_rate_limit" or backend.get("kind") != "valkey":
                continue
            for rule in item["rules"]:
                row = by_name[rule["name"]]
                window = window_seconds(rule.get("window"))
                timeout = window_seconds(rule.get("reservation_timeout", "30s"))
                if item.get("key", "global") != "global" or rule.get("algorithm") != "sliding_window":
                    row["balance_note"] = "Valkey reading supports global sliding_window rules only."
                elif not window or not timeout:
                    row["balance_note"] = "Valkey reading requires known positive window and reservation timeout."
                elif backend.get("url") != "${TOKEN_RATE_LIMIT_VALKEY_URL}":
                    row["balance_note"] = "Valkey reading requires the managed TOKEN_RATE_LIMIT_VALKEY_URL."
                else:
                    selected.append((backend, rule, row, int(window * 1000), int(timeout * 1000)))
    if not selected:
        return
    image = json.loads(service("podman", "inspect", "praxis-shared-gateway", "--format", "{{json .ImageName}}"))
    if image.rsplit("@", 1)[-1] != LEDGER_IMAGE:
        for _, _, row, _, _ in selected:
            row["balance_note"] = "Valkey ledger format is not qualified for this Praxis image."
        return
    # Capture the existing secret privately; never put credentials in argv or errors.
    connection = urlsplit(service("podman", "exec", "praxis-shared-gateway", "sh", "-c",
                                  'printf "%s" "$TOKEN_RATE_LIMIT_VALKEY_URL"').strip())
    user, password = unquote(connection.username or ""), unquote(connection.password or "")
    if (connection.scheme != "redis" or connection.hostname != "praxis-valkey"
            or connection.port not in (None, 6379) or connection.path not in ("", "/", "/0")
            or connection.query or connection.fragment or user != "praxis" or not password
            or any(character in password for character in "\r\n\0")):
        raise ValueError("Valkey reading requires the managed local praxis connection on database 0")
    for backend, rule, row, window, timeout in selected:
        keys = valkey_keys(backend.get("namespace", "praxis:token_rate_limit"), rule["name"])
        result = service("podman", "exec", "-i", "praxis-valkey", "sh", "-c",
                         'IFS= read -r VALKEYCLI_AUTH || exit 1; export VALKEYCLI_AUTH; '
                         'exec valkey-cli --no-auth-warning --json --user praxis "$@"',
                         "quota-status", "EVAL", LEDGER_READ, "2", *keys, str(window),
                         input_text=password + "\n")
        balance = valkey_balance(json.loads(result), window, timeout)
        remaining = max(0, row["capacity"] - balance["charged"])
        row.update(balance, remaining=remaining, basis="valkey ledger",
                   room_for_reservation=None if row["reservation"] is None else remaining >= row["reservation"])


def parse_metrics(text):
    points = {}
    for line in text.splitlines():
        if not line.startswith(PREFIX):
            continue
        match = re.fullmatch(r'(\w+)\{(.*)\}\s+(\S+)(?:\s+\d+)?', line)
        if not match:
            raise ValueError("unrecognized quota metric format")
        labels = {key: json.loads('"' + value + '"') for key, value in
                  re.findall(r'(\w+)="((?:\\.|[^"\\])*)"', match[2])}
        try:
            value = Decimal(match[3])
        except InvalidOperation as error:
            raise ValueError("invalid quota metric number") from error
        if not value.is_finite() or value < 0 or value != value.to_integral_value():
            raise ValueError("quota metrics must contain finite nonnegative integers")
        key = (match[1], tuple(sorted(labels.items())))
        if key in points:
            raise ValueError("duplicate quota metric series")
        points[key] = int(value)
    return points


def sample(points, suffix, rule, **labels):
    wanted = {"rule": rule, **labels}
    matches = [value for (name, fields), value in points.items()
               if name == PREFIX + suffix and wanted.items() <= dict(fields).items()]
    if len(matches) > 1:
        raise ValueError("ambiguous quota metrics for rule " + rule)
    return matches[0] if matches else None


def window_seconds(window):
    match = re.fullmatch(r'(\d+)(ms|s|m|h|d|w)', str(window))
    if not match:
        return None
    return int(match[1]) * {"ms": .001, "s": 1, "m": 60, "h": 3600,
                           "d": 86400, "w": 604800}[match[2]]


def balance_basis(item, rule, points, started, now, modified):
    """Only reconstruct the shipped global memory ledger before any aging."""
    if item.get("backend", {}).get("kind", "memory") != "memory":
        return "persistent"
    if rule.get("algorithm") != "sliding_window":
        return "algorithm"
    if item.get("key", "global") != "global" or (sample(points, "active_keys", rule["name"]) or 0) > 1:
        return "key scope"
    duration = window_seconds(rule.get("window"))
    age = (now - started).total_seconds()
    if duration is None or age < 0:
        return "unknown window"
    if modified > started:
        return "config changed"
    if age >= duration:
        return "window aged"
    return "first window"


def summarize(config, metrics, started, now, modified):
    points, rows, names = parse_metrics(metrics), [], set()
    for chain in config["filter_chains"]:
        for item in chain["filters"]:
            if item["filter"] != "token_rate_limit":
                continue
            for rule in item["rules"]:
                name = rule["name"]
                if name in names:
                    raise ValueError("quota rule names must be unique to interpret metrics")
                names.add(name)
                tokens = {kind: sample(points, "tokens_total", name, kind=kind)
                          for kind in ("estimated", "actual", "refunded", "overage")}
                net = None if tokens["estimated"] is None else (
                    tokens["estimated"] - (tokens["refunded"] or 0) + (tokens["overage"] or 0))
                basis = balance_basis(item, rule, points, started, now, modified)
                if net is None:
                    basis = "no samples"
                elif net < 0:
                    basis = "inconsistent"
                charged = net if basis == "first window" else None
                remaining = None if charged is None else max(0, rule["capacity"] - charged)
                reserve = rule.get("reserved_tokens")
                rows.append({"rule": name, "window": rule.get("window", "-"),
                    "backend": item.get("backend", {}).get("kind", "memory"),
                    "capacity": rule["capacity"], "reservation": reserve,
                    "charged": charged, "remaining": remaining, "basis": basis,
                    "room_for_reservation": None if remaining is None or reserve is None else remaining >= reserve,
                    "actual": tokens["actual"], "estimated_since_start": tokens["estimated"],
                    "net_since_start": net if item.get("backend", {}).get("kind", "memory") == "memory" else None,
                    "denied": sample(points, "requests_total", name, decision="denied") or (0 if net is not None else None),
                    "orphaned": sample(points, "reservations_total", name, result="orphaned") or
                    (0 if net is not None and item.get("backend", {}).get("kind", "memory") == "memory" else None)})
    return rows


def table(headers, rows):
    rows = [[str(value) for value in row] for row in rows]
    widths = [max(len(value) for value in column) for column in zip(headers, *rows)]
    return "\n".join("  ".join(value.ljust(width) for value, width in zip(row, widths)).rstrip()
                     for row in [headers, ["-" * width for width in widths], *rows])


def format_report(rows, started):
    def number(value):
        return "unknown" if value is None else f"{value:,}"

    output = ["Token quota snapshot; process started " + started.isoformat(), "",
        table(["Rule", "Backend", "Window", "Capacity", "Charged", "Remaining", "Reserve", "Denied", "Balance"],
              [[row["rule"], row["backend"], row["window"], *[number(row[key]) for key in
                ("capacity", "charged", "remaining", "reservation", "denied")], row["basis"]] for row in rows]),
        "", "Since process start (cumulative accounting, not rolling-window usage):",
        table(["Rule", "Reserved tokens", "Reconciled tokens", "Net charged tokens", "Orphaned requests"],
              [[row["rule"], *[number(row[key]) for key in ("estimated_since_start", "actual", "net_since_start", "orphaned")]] for row in rows]),
        "", "Unknown = unavailable accounting, not zero usage.",
        "Denied counts are cumulative. Snapshots can change while requests finish."]
    if any(row["backend"] == "memory" for row in rows):
        output.append("First window = estimated - refunded + overage. Memory quotas reset on Praxis restart.")
    if any(row["backend"] == "valkey" for row in rows):
        output.append("Valkey retains quota usage across Praxis restarts. Ledger charges include retained estimates "
                      "and outstanding reservations; reading does not change quotas.")
        output.append("This image omits Valkey settlement/refund counters; reserved tokens are not actual spend.")
    if any(row["basis"] == "no samples" for row in rows):
        output.append("No samples = this process has not emitted token-accounting samples for that rule yet. "
                      "Refresh after inference; missing samples do not imply zero saved usage.")
    for row in rows:
        if row.get("balance_note"):
            output.append(row["rule"] + ": " + row["balance_note"])
        if row["room_for_reservation"] is False:
            output.append(row["rule"] + ": remaining capacity is below the next request's reservation.")
    output += ["", "List rules and capacity-setting commands: sudo scripts/common/quota-set --list"]
    return "\n".join(output)


def service(*args, input_text=None):
    result = subprocess.run(["bash", "-c", 'source "$1"; shift; as_service "$@"',
                             "quota-status", str(LIB), *args], capture_output=True, text=True, input=input_text,
                            check=True, timeout=30)
    return result.stdout


def parse_started(value):
    # RHEL Python 3.9 needs microseconds rather than Podman's nanoseconds.
    normalized = re.sub(r'(\.\d{6})\d+', r'\1', value).replace("Z", "+00:00")
    started = datetime.fromisoformat(normalized)
    if started.tzinfo is None:
        raise ValueError("container start time has no timezone")
    return started


def collect():
    subprocess.run(["bash", "-c", 'source "$1"; verify_managed_manifest', "quota-status", str(LIB)],
                   check=True, capture_output=True, text=True, timeout=30)
    path = Path(os.environ.get("PRAXIS_CONFIG_DIR", "/etc/praxis")) / "shared-gateway.yaml"
    original, modified = path.read_bytes(), datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    command = ("podman", "inspect", "praxis-shared-gateway", "--format", "{{json .State.StartedAt}}")
    start = service(*command).strip()
    metrics = service("podman", "exec", "praxis-shared-gateway", "curl", "-fsS", "--max-time", "10",
                      "http://127.0.0.1:9901/metrics")
    started = parse_started(json.loads(start))
    config = yaml.safe_load(original)
    rows = summarize(config, metrics, started, datetime.now(timezone.utc), modified)
    read_valkey_balances(config, rows)
    if service(*command).strip() != start or path.read_bytes() != original:
        raise ValueError("gateway restarted or configuration changed while reading; retry")
    return started, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit structured output; unknown balances are null")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("run with sudo from the administrator deployment bundle")
    try:
        started, rows = collect()
    except (OSError, ValueError, InvalidOperation, yaml.YAMLError, subprocess.SubprocessError) as error:
        print("quota-status: could not read a consistent quota snapshot: " + str(error), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"process_started": started.isoformat(), "quotas": rows}, indent=2))
    else:
        print(format_report(rows, started))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
