#!/usr/bin/env bash

read_metadata_status() {
  python3 -c '
import json
import sys

metadata = json.load(sys.stdin)
required_strings = (
    "repository",
    "task_kind",
    "prompt_identifier",
    "base_ref",
    "base_commit",
    "branch",
    "proposed_pr_title",
    "summary",
)
for key in required_strings:
    value = metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SystemExit("metadata field must be a non-empty string: " + key)
for key in ("test_results", "known_risks"):
    if not isinstance(metadata.get(key), list):
        raise SystemExit("metadata field must be an array: " + key)
status = metadata.get("status")
if status not in ("success", "failed"):
    raise SystemExit("metadata status must be success or failed")
print(status)
'
}
