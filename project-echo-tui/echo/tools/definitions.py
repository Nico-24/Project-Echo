"""
Tool definitions for native Ollama/OpenAI tool calling.
Falls back to action-block parsing for models without tool support.
"""
from __future__ import annotations
import json
import re
from pathlib import Path


TOOLS = [
    {"type": "function", "function": {
        "name": "create_file",
        "description": "Create or overwrite a file with complete content.",
        "parameters": {"type": "object", "required": ["path", "content", "description"],
            "properties": {
                "path":        {"type": "string", "description": "Relative path from project root"},
                "content":     {"type": "string", "description": "Complete file content"},
                "description": {"type": "string", "description": "What this file does"},
            }},
    }},
    {"type": "function", "function": {
        "name": "edit_file",
        "description": "Edit an existing file. Provide the complete new content.",
        "parameters": {"type": "object", "required": ["path", "content", "description"],
            "properties": {
                "path":        {"type": "string"},
                "content":     {"type": "string", "description": "Complete new file content"},
                "description": {"type": "string"},
            }},
    }},
    {"type": "function", "function": {
        "name": "delete_file",
        "description": "Delete a file or folder.",
        "parameters": {"type": "object", "required": ["path", "description"],
            "properties": {
                "path":        {"type": "string"},
                "description": {"type": "string"},
            }},
    }},
    {"type": "function", "function": {
        "name": "move_file",
        "description": "Move or rename a file.",
        "parameters": {"type": "object", "required": ["path", "destination", "description"],
            "properties": {
                "path":        {"type": "string"},
                "destination": {"type": "string"},
                "description": {"type": "string"},
            }},
    }},
    {"type": "function", "function": {
        "name": "create_directory",
        "description": "Create a directory.",
        "parameters": {"type": "object", "required": ["path", "description"],
            "properties": {
                "path":        {"type": "string"},
                "description": {"type": "string"},
            }},
    }},
    {"type": "function", "function": {
        "name": "run_command",
        "description": "Run a shell command in the project root.",
        "parameters": {"type": "object", "required": ["command", "description"],
            "properties": {
                "command":     {"type": "string"},
                "description": {"type": "string"},
            }},
    }},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a file to understand it before making changes.",
        "parameters": {"type": "object", "required": ["path"],
            "properties": {"path": {"type": "string"}}},
    }},
    {"type": "function", "function": {
        "name": "search_code",
        "description": "Search for text across all project files.",
        "parameters": {"type": "object", "required": ["query"],
            "properties": {
                "query":        {"type": "string"},
                "file_pattern": {"type": "string", "default": "*"},
            }},
    }},
]

TOOL_CAPABLE = {
    "qwen2.5", "qwen2.5-coder", "qwen3", "llama3.1", "llama3.2", "llama3.3",
    "mistral-nemo", "mistral-large", "deepseek-coder-v2", "command-r",
    "hermes3", "nemotron-mini", "firefunction",
}


def model_supports_tools(model: str) -> bool:
    name = model.lower().split(":")[0]
    return any(t in name for t in TOOL_CAPABLE)


# ── Action block fallback parser ──────────────────────────────────────────────

def parse_action_blocks(text: str) -> list[dict]:
    """Extract action blocks from model output (fallback for non-tool models)."""
    results = []

    # Strategy 1: ```action ... ```
    for m in re.finditer(r"```(?:action|ACTION)\s*([\s\S]*?)```", text, re.IGNORECASE):
        parsed = _try_parse_json(m.group(1).strip())
        if parsed and parsed.get("action"):
            results.append(parsed)
    if results:
        return results

    # Strategy 2: ```json ... ``` with action field
    for m in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE):
        parsed = _try_parse_json(m.group(1).strip())
        if parsed and parsed.get("action") and parsed.get("path") is not None:
            results.append(parsed)
    if results:
        return results

    # Strategy 3: bare JSON with action field
    for m in re.finditer(
        r'\{"action"\s*:\s*"(create|edit|delete|move|mkdir|shell|read|search)"[^}]*\}',
        text, re.IGNORECASE
    ):
        parsed = _try_parse_json(m.group(0))
        if parsed:
            results.append(parsed)
    return results


def _try_parse_json(raw: str) -> dict | None:
    try:
        return json.loads(raw)
    except Exception:
        pass
    try:
        fixed = re.sub(r'("(?:[^"\\]|\\.)*")|(\n)', lambda m: m.group(1) or "\\n", raw)
        return json.loads(fixed)
    except Exception:
        pass
    # Manual extraction fallback
    try:
        def get(key: str) -> str | None:
            m = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
            return m.group(1) if m else None
        action = get("action")
        path   = get("path") or ""
        if not action:
            return None
        content_start = raw.find('"content"')
        content = None
        if content_start != -1:
            q = raw.index('"', content_start + 10)
            end = q + 1
            while end < len(raw) and not (raw[end] == '"' and raw[end-1] != '\\'):
                end += 1
            content = raw[q+1:end].replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')
        return {
            "action":      action,
            "path":        path,
            "content":     content,
            "description": get("description") or "",
            "destination": get("destination"),
            "command":     get("command"),
            "query":       get("query"),
        }
    except Exception:
        return None


def tool_call_to_action(name: str, args: dict) -> dict:
    """Convert a tool call to a unified action dict."""
    name_map = {
        "create_file": "create", "edit_file": "edit",
        "delete_file": "delete", "move_file": "move",
        "create_directory": "mkdir", "run_command": "shell",
        "read_file": "read", "search_code": "search",
    }
    return {
        "action":      name_map.get(name, name),
        "path":        args.get("path", ""),
        "content":     args.get("content"),
        "destination": args.get("destination"),
        "command":     args.get("command"),
        "query":       args.get("query"),
        "description": args.get("description", ""),
    }
