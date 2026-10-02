#!/usr/bin/env python3
"""Preserve administrator quota capacities across provider changes and upgrades."""
import argparse
import copy
import json
from pathlib import Path


def capacity(value):
    if type(value) is not int or not 0 < value < 2**64:
        raise ValueError("capacity must be a positive 64-bit integer")
    return value


def entries(config):
    """One entry per distinct budget; identical Valkey rules can share a ledger."""
    result = {}
    for chain in config["filter_chains"]:
        for item in chain["filters"]:
            if item["filter"] != "token_rate_limit":
                continue
            for rule in item["rules"]:
                name = rule["name"]
                if name in result:
                    previous, old = result[name]
                    if (item.get('backend', {}).get('kind') != 'valkey'
                            or item.get('backend') != previous.get('backend')
                            or item.get('key', 'global') != previous.get('key', 'global')
                            or old != rule):
                        raise ValueError('quota rule names must be unique unless sharing identical Valkey settings')
                else:
                    result[name] = (item, rule)
    return result


def rules(config):
    return {name: rule for name, (_, rule) in entries(config).items()}


def validate(overrides):
    if not isinstance(overrides, dict):
        raise ValueError("quota overrides must map rule names to capacities")
    for name, value in overrides.items():
        if not isinstance(name, str) or not name or any(c.isspace() for c in name):
            raise ValueError("quota override has an invalid rule name")
        capacity(value)
    return overrides


def load(path):
    return validate(json.loads(path.read_text())) if path.exists() else {}


def minimum_capacity(rule):
    if rule.get("algorithm") != "sliding_window" or "reserved_tokens" not in rule:
        raise ValueError("requires sliding_window with explicit reserved_tokens")
    reserve = rule["reserved_tokens"]
    if type(reserve) is not int or not 0 <= reserve < 2**64:
        raise ValueError("reserved_tokens must be a nonnegative 64-bit integer")
    return max(1, reserve)


def apply(original, overrides):
    """Inactive providers retain saved capacities until they are enabled again."""
    validate(overrides)
    result = copy.deepcopy(original)
    rules(result)  # Validate duplicates before changing every copy of a shared rule.
    all_rules = [r for c in result['filter_chains'] for f in c['filters']
                 if f['filter'] == 'token_rate_limit' for r in f['rules']]
    for rule in all_rules:
        name = rule['name']
        if name not in overrides:
            continue
        if overrides[name] < minimum_capacity(rule):
            raise ValueError(f"{name}: capacity must cover reserved_tokens ({rule['reserved_tokens']})")
        rule["capacity"] = overrides[name]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--overrides", type=Path, required=True)
    args = parser.parse_args()
    import yaml
    config = apply(yaml.safe_load(args.config.read_text()), load(args.overrides))
    args.config.write_text(json.dumps(config, indent=2) + "\n")


if __name__ == "__main__":
    main()
