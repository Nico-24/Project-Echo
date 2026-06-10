"""
Ollama and OpenAI-compatible providers with tool calling support.
Both yield either str (text chunks) or dict {"tool_call": {name, arguments}}.
"""
from __future__ import annotations
import json
from typing import AsyncIterator

import httpx


class OllamaProvider:
    def __init__(self, base_url: str = "http://localhost", port: int = 11434):
        self.url = f"{base_url}:{port}"

    async def stream(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[str | dict]:
        payload: dict = {"model": model, "messages": messages, "stream": True}
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", f"{self.url}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        msg  = data.get("message", {})

                        for tc in msg.get("tool_calls", []):
                            fn   = tc.get("function", {})
                            name = fn.get("name", "")
                            args = fn.get("arguments", {})
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except Exception:
                                    args = {}
                            yield {"tool_call": {"name": name, "arguments": args}}

                        chunk = msg.get("content", "")
                        if chunk:
                            yield chunk

                        if data.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self.url}/api/tags")
            resp.raise_for_status()
            return [m["name"] for m in resp.json().get("models", [])]

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                return (await client.get(f"{self.url}/api/tags")).status_code == 200
        except Exception:
            return False


class OpenAICompatProvider:
    def __init__(self, base_url: str = "http://localhost", port: int = 1234):
        self.url = f"{base_url}:{port}"

    async def stream(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[str | dict]:
        payload: dict = {"model": model, "messages": messages, "stream": True}
        if tools:
            payload["tools"] = tools

        tc_buf: dict[int, dict] = {}

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST", f"{self.url}/v1/chat/completions",
                json=payload,
                headers={"Authorization": "Bearer local"},
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or line == "data: [DONE]":
                        continue
                    if not line.startswith("data: "):
                        continue
                    try:
                        data  = json.loads(line[6:])
                        delta = data.get("choices", [{}])[0].get("delta", {})

                        for tc in delta.get("tool_calls", []):
                            idx = tc.get("index", 0)
                            if idx not in tc_buf:
                                tc_buf[idx] = {"name": "", "arguments": ""}
                            fn = tc.get("function", {})
                            tc_buf[idx]["name"]      += fn.get("name", "")
                            tc_buf[idx]["arguments"] += fn.get("arguments", "")

                        chunk = delta.get("content", "")
                        if chunk:
                            yield chunk

                        if data.get("choices", [{}])[0].get("finish_reason") == "tool_calls":
                            for tc in tc_buf.values():
                                try:
                                    args = json.loads(tc["arguments"])
                                except Exception:
                                    args = {}
                                yield {"tool_call": {"name": tc["name"], "arguments": args}}
                            tc_buf.clear()
                    except json.JSONDecodeError:
                        continue

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.url}/v1/models",
                                        headers={"Authorization": "Bearer local"})
                return [m["id"] for m in resp.json().get("data", [])]
        except Exception:
            return []

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{self.url}/v1/models",
                                     headers={"Authorization": "Bearer local"})
                return r.status_code in (200, 404)
        except Exception:
            return False
