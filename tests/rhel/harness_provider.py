#!/usr/bin/env python3
"""Add deterministic real-CLI tool turns to the shared synthetic LLM fixture."""
import json
from pathlib import Path
import shlex
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
import provider

original_completion = provider.completion
original_continuation = provider.continuation
MARKER = "PRAXIS_SMOKE_TOOL_OK"
PROGRAM = '''from pathlib import Path
Path("add.py").write_text("def add(a, b):\\n    return a + b\\n")
Path("test_add.py").write_text("import unittest\\nfrom add import add\\nclass TestAdd(unittest.TestCase):\\n    def test_values(self):\\n        self.assertEqual(add(2, 3), 5)\\n        self.assertEqual(add(-2, -3), -5)\\n        self.assertEqual(add(0, 0), 0)\\n")
import subprocess
subprocess.run(["python3", "-m", "unittest", "-v"], check=True)
print("PRAXIS_SMOKE_TOOL_OK")
'''
COMMAND = "python3 -c " + shlex.quote(PROGRAM)


def continuation(path, body):
    if original_continuation(path, body):
        return True
    items = body.get("input", []) if path == "/v1/responses" else body.get("messages", [])
    if not isinstance(items, list):
        return False
    for item in items:
        if item.get("type") == "function_call_output" and item.get("call_id") == "call_fixture":
            return MARKER in str(item.get("output", ""))
        if item.get("role") == "tool" and item.get("tool_call_id") == "call_fixture":
            return MARKER in str(item.get("content", ""))
        content = item.get("content", [])
        if isinstance(content, list):
            for part in content:
                if part.get("type") == "tool_result" and part.get("tool_use_id") == "call_fixture":
                    return not part.get("is_error") and MARKER in str(part.get("content", ""))
    return False


def tool_spec(body):
    for item in body.get("tools", []):
        tool = item.get("function", item)
        name = tool.get("name", "")
        if name in ("exec_command", "shell_command", "Bash", "bash", "shell"):
            if name == "exec_command":
                arguments = {"cmd": COMMAND, "max_output_tokens": 1000}
            elif name == "shell":
                arguments = {"command": ["bash", "-lc", COMMAND], "timeout_ms": 10000}
            else:
                arguments = {"command": COMMAND}
                if name == "bash":
                    arguments["description"] = "Run deterministic smoke test"
            return name, arguments
    return None


def completion(path, body, missing_usage=False):
    selected = tool_spec(body)
    if not selected:
        return original_completion(path, body, missing_usage)
    continued = continuation(path, body)
    # Reuse the protocol fixtures, replacing only tool identity and payload.
    result = original_completion(path, body, missing_usage)
    name, arguments = selected
    if path == "/v1/responses":
        item = result["output"][0]
        if continued:
            item["content"][0]["text"] = MARKER
        else:
            item.update(name=name, arguments=json.dumps(arguments))
    elif path == "/v1/chat/completions":
        message = result["choices"][0]["message"]
        if continued:
            message["content"] = MARKER
        else:
            message["tool_calls"][0]["function"] = {"name": name, "arguments": json.dumps(arguments)}
    else:
        item = result["content"][0]
        if continued:
            item["text"] = MARKER
        else:
            item.update(name=name, input=arguments)
    return result


def main():
    provider.continuation = continuation
    provider.completion = completion
    fixture = provider.Provider(host="0.0.0.0")
    fixture.start()
    qwen = provider.Provider(host="0.0.0.0", ports=(8000, 8001, 19001), model="qwen3-8b", local=True)
    qwen.start()
    threading.Event().wait()


if __name__ == "__main__":
    main()
