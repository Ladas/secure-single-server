#!/usr/bin/env python3
"""Compatibility entry point for the remote memory/Valkey contract suite."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
from gateway import main

if __name__ == "__main__":
    main(["--scenario", "remote", *sys.argv[1:]])
