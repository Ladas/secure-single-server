"""Independent assertions for the small protocol subset used by the fixtures."""
import json


def check(path, body, stream=False, tool=False, continued=False, model="fixture"):
    expected_text = "5" if continued else "mock answer"
    if not stream:
        result = json.loads(body)
    else:
        chunks = [line[6:] for line in body.splitlines() if line.startswith("data: ")]
        assert chunks, "no SSE events"
        values = [json.loads(chunk) for chunk in chunks if chunk != "[DONE]"]
        if path == "/v1/chat/completions":
            assert chunks[-1] == "[DONE]", "missing chat stream terminator"
            assert all(value["object"] == "chat.completion.chunk" for value in values)
            choices = [choice for value in values for choice in value["choices"]]
            deltas = [choice["delta"] for choice in choices]
            message = {"content": "".join(delta.get("content") or "" for delta in deltas)}
            calls = [call for delta in deltas for call in delta.get("tool_calls", [])]
            if calls:
                assert calls[0]["id"] == "call_fixture" and calls[0]["function"]["name"] == "add"
                message["tool_calls"] = [{"id": calls[0]["id"], "type": "function", "function": {
                    "name": calls[0]["function"]["name"],
                    "arguments": "".join(call["function"].get("arguments", "") for call in calls)}}]
            result = {"model": values[0]["model"], "usage": values[-1]["usage"],
                      "choices": [{"message": message, "finish_reason": choices[-1]["finish_reason"]}]}
        elif path == "/v1/responses":
            assert values[0]["type"] == "response.created"
            assert values[-1]["type"] == "response.completed", "missing responses stream terminator"
            assert [value["sequence_number"] for value in values] == list(range(len(values)))
            result = values[-1]["response"]
            delta_kind = "response.function_call_arguments.delta" if tool else "response.output_text.delta"
            deltas = "".join(value["delta"] for value in values if value["type"] == delta_kind)
            if tool:
                assert json.loads(deltas) == {"a": 2, "b": 3}
            else:
                assert deltas == expected_text
        else:
            assert values[0]["type"] == "message_start"
            assert values[-1]["type"] == "message_stop", "missing messages stream terminator"
            result = dict(values[0]["message"])
            final = next(value for value in values if value["type"] == "message_delta")
            result["usage"] = {**result["usage"], **final["usage"]}
            result["stop_reason"] = final["delta"]["stop_reason"]
            block = dict(next(value["content_block"] for value in values if value["type"] == "content_block_start"))
            deltas = [value["delta"] for value in values if value["type"] == "content_block_delta"]
            if tool:
                block["input"] = json.loads("".join(delta["partial_json"] for delta in deltas))
            else:
                block["text"] = "".join(delta["text"] for delta in deltas)
            result["content"] = [block]
    assert result["model"] == model
    usage = result["usage"]
    if path == "/v1/chat/completions":
        assert usage == {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}
        choice = result["choices"][0]
        assert choice["finish_reason"] == ("tool_calls" if tool else "stop")
        if tool:
            call = choice["message"]["tool_calls"][0]
            assert call["id"] == "call_fixture" and call["type"] == "function"
            assert call["function"]["name"] == "add"
            assert json.loads(call["function"]["arguments"]) == {"a": 2, "b": 3}
        else:
            assert choice["message"]["content"] == expected_text
    elif path == "/v1/responses":
        assert usage == {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5}
        assert result["status"] == "completed"
        item = result["output"][0]
        if tool:
            assert item["type"] == "function_call" and item["call_id"] == "call_fixture"
            assert item["name"] == "add" and json.loads(item["arguments"]) == {"a": 2, "b": 3}
        else:
            assert item["type"] == "message" and item["role"] == "assistant"
            assert item["content"][0]["type"] == "output_text" and item["content"][0]["text"] == expected_text
    else:
        assert usage == {"input_tokens": 2, "output_tokens": 3}
        assert result["stop_reason"] == ("tool_use" if tool else "end_turn")
        block = result["content"][0]
        if tool:
            assert block == {"type": "tool_use", "id": "call_fixture", "name": "add", "input": {"a": 2, "b": 3}}
        else:
            assert block == {"type": "text", "text": expected_text}
