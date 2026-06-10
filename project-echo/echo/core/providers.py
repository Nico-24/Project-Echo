"""LLM providers for Project Echo.

Both providers expose the same interface:

    async for chunk in provider.stream(messages, model, tools):
        # chunk is either a str (text delta) or
        # {"tool_call": {"name": str, "arguments": dict}}

    await provider.list_models() -> list[str]
    await provider.health() -> bool
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import httpx

debug_log = logging.getLogger("echo.debug")

STREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)
QUICK_TIMEOUT = httpx.Timeout(10.0)


class ProviderError(Exception):
    """Raised when a provider request fails."""


def _join_base(base_url: str, port: int | None) -> str:
    """Append :port to the base url unless it already carries an explicit port
    (e.g. "http://localhost" + 11434 -> "http://localhost:11434")."""
    base = (base_url or "http://localhost").rstrip("/")
    if not port:
        return base
    scheme, sep, rest = base.partition("://")
    host = (rest if sep else base).split("/")[0]
    if ":" in host.rpartition("@")[-1]:
        return base  # already has a port
    return f"{base}:{port}"


class OllamaProvider:
    """Streams chat completions from a local Ollama server."""

    name = "ollama"

    def __init__(self, base_url: str = "http://localhost", port: int | None = 11434):
        self.base = _join_base(base_url, port)

    async def stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[str | dict]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

        debug_log.debug(
            "[provider] POST %s/api/chat model=%s stream=True tools=%s",
            self.base, model,
            [t["function"]["name"] for t in tools] if tools else "NONE",
        )

        try:
            async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client:
                async with client.stream(
                    "POST", f"{self.base}/api/chat", json=payload
                ) as response:
                    if response.status_code != 200:
                        body = (await response.aread()).decode("utf-8", "replace")
                        raise ProviderError(
                            f"Ollama returned HTTP {response.status_code}: {body[:300]}"
                        )
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if data.get("error"):
                            raise ProviderError(f"Ollama error: {data['error']}")
                        message = data.get("message") or {}
                        content = message.get("content")
                        if content:
                            yield content
                        # Native tool calls (Ollama tool-capable models).
                        if message.get("tool_calls"):
                            debug_log.debug(
                                "[provider] native tool_calls in stream: %s",
                                json.dumps(message["tool_calls"])[:500],
                            )
                        for call in message.get("tool_calls") or []:
                            fn = call.get("function") or {}
                            args = fn.get("arguments") or {}
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except json.JSONDecodeError:
                                    args = {"_raw": args}
                            yield {
                                "tool_call": {
                                    "name": fn.get("name", ""),
                                    "arguments": args,
                                }
                            }
                        if data.get("done"):
                            return
        except httpx.HTTPError as exc:
            raise ProviderError(f"Could not reach Ollama at {self.base}: {exc}") from exc

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=QUICK_TIMEOUT) as client:
                response = await client.get(f"{self.base}/api/tags")
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise ProviderError(f"Could not list models from {self.base}: {exc}") from exc
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=QUICK_TIMEOUT) as client:
                response = await client.get(f"{self.base}/api/tags")
                return response.status_code == 200
        except httpx.HTTPError:
            return False


class OpenAICompatProvider:
    """Streams chat completions from any OpenAI-compatible endpoint
    (LM Studio, llama.cpp server, vLLM, text-generation-webui, ...)."""

    name = "openai"

    def __init__(
        self,
        base_url: str = "http://localhost",
        port: int | None = 1234,
        api_key: str = "",
    ):
        base = _join_base(base_url, port)
        if not base.endswith("/v1"):
            base = base + "/v1"
        self.base = base
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[str | dict]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

        # Tool-call fragments arrive split across chunks keyed by index;
        # accumulate and emit complete calls at the end of the stream.
        pending_calls: dict[int, dict[str, str]] = {}

        try:
            async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client:
                async with client.stream(
                    "POST",
                    f"{self.base}/chat/completions",
                    json=payload,
                    headers=self._headers(),
                ) as response:
                    if response.status_code != 200:
                        body = (await response.aread()).decode("utf-8", "replace")
                        raise ProviderError(
                            f"Server returned HTTP {response.status_code}: {body[:300]}"
                        )
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        choices = data.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        content = delta.get("content")
                        if content:
                            yield content
                        for frag in delta.get("tool_calls") or []:
                            index = frag.get("index", 0)
                            slot = pending_calls.setdefault(
                                index, {"name": "", "arguments": ""}
                            )
                            fn = frag.get("function") or {}
                            if fn.get("name"):
                                slot["name"] += fn["name"]
                            if fn.get("arguments"):
                                slot["arguments"] += fn["arguments"]
        except httpx.HTTPError as exc:
            raise ProviderError(f"Could not reach server at {self.base}: {exc}") from exc

        for index in sorted(pending_calls):
            slot = pending_calls[index]
            if not slot["name"]:
                continue
            try:
                args = json.loads(slot["arguments"]) if slot["arguments"] else {}
            except json.JSONDecodeError:
                args = {"_raw": slot["arguments"]}
            yield {"tool_call": {"name": slot["name"], "arguments": args}}

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=QUICK_TIMEOUT) as client:
                response = await client.get(f"{self.base}/models", headers=self._headers())
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise ProviderError(f"Could not list models from {self.base}: {exc}") from exc
        return [m.get("id", "") for m in data.get("data", []) if m.get("id")]

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=QUICK_TIMEOUT) as client:
                response = await client.get(f"{self.base}/models", headers=self._headers())
                return response.status_code == 200
        except httpx.HTTPError:
            return False
