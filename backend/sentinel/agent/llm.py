"""LLM providers behind one tiny interface.

Messages use the OpenAI chat shape internally:
  {"role": "system"|"user"|"assistant"|"tool", "content": str, "tool_calls": [...], "tool_call_id": str}
Each provider returns an `LLMReply` with plain text and normalized tool calls.
"""
import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from sentinel.config import settings

log = logging.getLogger(__name__)


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class LLMReply:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    # The provider's tool calls exactly as received. Gemini 3 attaches a thought_signature to each call and
    # rejects the next request unless it comes back unchanged, so we replay them verbatim.
    raw_tool_calls: list[dict] | None = None

    def as_message(self) -> dict:
        msg: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.raw_tool_calls:
            msg["tool_calls"] = self.raw_tool_calls
        elif self.tool_calls:
            msg["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.args)}}
                for c in self.tool_calls
            ]
        return msg


class LLM(Protocol):
    name: str

    async def chat(self, messages: list[dict], tools: list[dict]) -> LLMReply: ...


def _parse_args(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        out = json.loads(raw or "{}")
        return out if isinstance(out, dict) else {}
    except json.JSONDecodeError:
        return {}


async def _post_with_retry(client: httpx.AsyncClient, url: str, body: dict, headers: dict | None = None) -> dict:
    """POST with backoff on rate limits / overload, which free tiers hit during demos."""
    delay = 2.0
    for attempt in range(4):
        resp = await client.post(url, json=body, headers=headers or {})
        if resp.status_code in (429, 500, 502, 503) and attempt < 3:
            wait_s = delay
            retry_header = resp.headers.get("retry-after")
            if retry_header:
                try:
                    wait_s = max(float(retry_header), delay)
                except (ValueError, TypeError):
                    pass
            if wait_s > 4.0:
                raise RuntimeError(f"Rate limited by {url} (wait {wait_s:.1f}s), falling over")
            log.warning("LLM %s returned %s, retrying in %.1fs", url, resp.status_code, wait_s)
            await asyncio.sleep(wait_s)
            delay = max(delay * 2, wait_s + 1.0)
            continue
        if resp.status_code >= 400:
            raise RuntimeError(f"LLM error {resp.status_code}: {resp.text[:300]}")
        return resp.json()
    raise RuntimeError("unreachable")


class OllamaLLM:
    """Local model through Ollama's native /api/chat (lets us turn qwen3's hidden thinking off)."""

    def __init__(self, model: str, url: str, num_ctx: int = 12288):
        self.model, self.url, self.num_ctx = model, url.rstrip("/"), num_ctx
        self.name = f"ollama:{model}"
        self._client = httpx.AsyncClient(timeout=180)

    def _convert(self, messages: list[dict]) -> list[dict]:
        out = []
        names: dict[str, str] = {}
        for m in messages:
            if m["role"] == "assistant" and m.get("tool_calls"):
                calls = []
                for c in m["tool_calls"]:
                    names[c["id"]] = c["function"]["name"]
                    calls.append({"function": {"name": c["function"]["name"],
                                               "arguments": _parse_args(c["function"]["arguments"])}})
                out.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls})
            elif m["role"] == "tool":
                out.append({"role": "tool", "content": m["content"], "tool_name": names.get(m["tool_call_id"], "")})
            else:
                out.append({"role": m["role"], "content": m.get("content") or ""})
        return out

    async def chat(self, messages: list[dict], tools: list[dict]) -> LLMReply:
        body = {"model": self.model, "messages": self._convert(messages), "tools": tools, "stream": False,
                "think": False, "keep_alive": "30m", "options": {"num_ctx": self.num_ctx, "temperature": 0.2}}
        data = await _post_with_retry(self._client, f"{self.url}/api/chat", body)
        msg = data.get("message", {})
        calls = [ToolCall(id=f"call_{uuid.uuid4().hex[:8]}", name=c["function"]["name"],
                          args=_parse_args(c["function"].get("arguments")))
                 for c in msg.get("tool_calls") or []]
        return LLMReply(content=(msg.get("content") or "").strip(), tool_calls=calls)


class OpenAICompatLLM:
    """Any OpenAI-compatible chat API: Gemini (/v1beta/openai), Groq, OpenRouter, vLLM, OpenAI."""

    def __init__(self, model: str, base_url: str, api_key: str | list[str], label: str = "openai"):
        self.model, self.base_url = model, base_url.rstrip("/")
        if isinstance(api_key, list):
            self.api_keys = [k.strip() for k in api_key if k.strip()]
        else:
            self.api_keys = [k.strip() for k in str(api_key).split(",") if k.strip()]
        self.key_index = 0
        self.name = f"{label}:{model}"
        self._client = httpx.AsyncClient(timeout=120)

    @property
    def current_key(self) -> str:
        return self.api_keys[self.key_index] if self.api_keys else ""

    def rotate_key(self) -> str:
        if len(self.api_keys) > 1:
            self.key_index = (self.key_index + 1) % len(self.api_keys)
            log.warning("Rotated to API key #%d/%d", self.key_index + 1, len(self.api_keys))
        return self.current_key

    async def chat(self, messages: list[dict], tools: list[dict]) -> LLMReply:
        body = {"model": self.model, "messages": messages, "tools": tools, "temperature": 0.2}
        attempts = max(len(self.api_keys), 1)
        last_exc: Exception | None = None
        for _ in range(attempts):
            headers = {"Authorization": f"Bearer {self.current_key}"}
            try:
                data = await _post_with_retry(self._client, f"{self.base_url}/chat/completions", body, headers)
                msg = data["choices"][0]["message"]
                raw = msg.get("tool_calls") or []
                for c in raw:  # every call needs an id so tool results can refer to it
                    c.setdefault("id", f"call_{uuid.uuid4().hex[:8]}")
                    c.setdefault("type", "function")
                calls = [ToolCall(id=c["id"], name=c["function"]["name"], args=_parse_args(c["function"].get("arguments")))
                         for c in raw]
                return LLMReply(content=(msg.get("content") or "").strip(), tool_calls=calls, raw_tool_calls=raw or None)
            except Exception as exc:
                last_exc = exc
                if len(self.api_keys) > 1 and ("429" in str(exc) or "rate limit" in str(exc).lower()):
                    self.rotate_key()
                    continue
                raise
        if last_exc:
            raise last_exc


GEMINI_OPENAI_URL = "https://generativelanguage.googleapis.com/v1beta/openai"


def make_llm(provider: str | None = None) -> LLM:
    """Build the provider named by LLM_PROVIDER: ollama (default) | gemini | openai | autopilot."""
    provider = (provider or settings.llm_provider).lower()
    if provider == "ollama":
        return OllamaLLM(settings.ollama_model, settings.ollama_url)
    if provider == "gemini":
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        keys = [k.strip() for k in settings.gemini_api_key.split(",") if k.strip()]
        model = settings.llm_model if (settings.llm_model and "gemini" in settings.llm_model) else "gemini-flash-latest"
        return OpenAICompatLLM(model, GEMINI_OPENAI_URL, keys, "gemini")
    if provider == "openai":
        if not (settings.openai_base_url and settings.openai_api_key and settings.llm_model):
            raise RuntimeError("set OPENAI_BASE_URL, OPENAI_API_KEY and LLM_MODEL")
        keys = [k.strip() for k in settings.openai_api_key.split(",") if k.strip()]
        return OpenAICompatLLM(settings.llm_model, settings.openai_base_url, keys)
    if provider == "autopilot":
        from .autopilot import Autopilot

        return Autopilot(settings.autopilot_delay_s)
    raise RuntimeError(f"unknown LLM_PROVIDER {provider!r}")


def available_providers() -> list[str]:
    """Providers that can actually run here (shown in the UI's model picker)."""
    out = []
    try:
        httpx.get(f"{settings.ollama_url.rstrip('/')}/api/tags", timeout=1.0).raise_for_status()
        out.append("ollama")
    except Exception:  # noqa: BLE001 - not running / not reachable
        pass
    if settings.gemini_api_key:
        out.append("gemini")
    if settings.openai_base_url and settings.openai_api_key and settings.llm_model:
        out.append("openai")
    out.append("autopilot")
    return out
