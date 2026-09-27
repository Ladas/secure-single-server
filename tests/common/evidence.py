"""Bounded evidence containing no headers, keys, tokens or request bodies."""
import json
import os
from pathlib import Path
import re


def redact(text):
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    text = re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[JWT REDACTED]", text)
    text = re.sub(r"(?i)Bearer\s+[^\s,}\]\"']+", "Bearer [REDACTED]", text)
    text = re.sub(r"(?i)(authorization|x-api-key|api_key|password)([\s\"':=]+)[^\s,}\]]+",
                  r"\1\2[REDACTED]", text)
    text = re.sub(r"synthetic-[a-z-]+|local-valkey-test", "[SYNTHETIC SECRET]", text)
    return text[-16000:]


def save(name, result):
    def scrub(value):
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return redact(value) if isinstance(value, str) else value

    directory = Path(os.environ.get("TEST_EVIDENCE_DIR", "evidence/mocked-provider"))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.json").write_text(json.dumps(scrub(result), indent=2) + "\n")
