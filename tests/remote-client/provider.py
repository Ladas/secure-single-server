#!/usr/bin/env python3
"""Deterministic model behind the local HTTPS gateway; inference stays private."""
from pathlib import Path
import sys
import threading

TESTS = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TESTS / "rhel"), str(TESTS / "common")]
import harness_provider as harness

harness.provider.completion = harness.completion
harness.provider.continuation = harness.continuation
harness.provider.Provider(control_host="0.0.0.0").start()
harness.provider.Provider(ports=(8000, 8001, 19001), model="qwen3-8b", local=True).start()
threading.Event().wait()
