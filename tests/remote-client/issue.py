#!/usr/bin/env python3
"""Administrator: issue two synthetic subjects and a signed expired JWT for client tests."""
import argparse
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/common"))
from gateway import token


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", type=Path, required=True, help="existing test issuer private key; keep it on the administrator workstation")
    parser.add_argument("--output", type=Path, required=True, help="new private directory; must not exist")
    args = parser.parse_args()
    if not args.key.is_file():
        parser.error("issuer key does not exist")
    args.output.mkdir(mode=0o700, parents=True)
    for name, subject, expiry in (("caller.jwt", "external-client-one", int(time.time()) + 86400),
                                  ("second.jwt", "external-client-two", int(time.time()) + 86400),
                                  ("expired.jwt", "external-client-expired", int(time.time()) - 600)):
        value = token(args.key, sub=subject, exp=expiry)
        with (args.output / name).open("x") as target:
            os.fchmod(target.fileno(), 0o600)
            target.write(value + "\n")
    print("Caller JWT files created in " + str(args.output) + "; issuer key was not copied.")


if __name__ == "__main__":
    main()
