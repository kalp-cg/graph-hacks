"""Provider adapters, against a fake OpenAI-compatible server that behaves like Gemini 3."""
import asyncio
import json

import httpx

from sentinel.agent.llm import OpenAICompatLLM

SIGNATURE = "opaque-signature-123"


def gemini_like(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    assistant_calls = [c for m in body["messages"] if m["role"] == "assistant" for c in m.get("tool_calls") or []]
    # Like Gemini 3: every function call sent back must carry its thought_signature.
    if any(c.get("extra_content", {}).get("google", {}).get("thought_signature") != SIGNATURE for c in assistant_calls):
        return httpx.Response(400, json={"error": {"message": "Function call is missing a thought_signature"}})
    if assistant_calls:
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "done"}}]})
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [{
        "id": "call_1", "type": "function", "function": {"name": "get_active_alerts", "arguments": "{}"},
        "extra_content": {"google": {"thought_signature": SIGNATURE}},
    }]}}]})


def test_tool_call_signatures_are_sent_back():
    llm = OpenAICompatLLM("gemini-test", "https://fake.local/v1", "key", "gemini")
    llm._client = httpx.AsyncClient(transport=httpx.MockTransport(gemini_like))

    async def go():
        messages = [{"role": "user", "content": "investigate"}]
        first = await llm.chat(messages, [])
        assert first.tool_calls[0].name == "get_active_alerts"
        messages += [first.as_message(), {"role": "tool", "tool_call_id": "call_1", "content": "[]"}]
        second = await llm.chat(messages, [])  # a 400 here raises
        return second.content

    assert asyncio.run(go()) == "done"
