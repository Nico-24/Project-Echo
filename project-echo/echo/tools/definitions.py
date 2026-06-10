"""Tool definitions, capability detection and action-block parsing."""

from __future__ import annotations

import json
import re

# ---------------------------------------------------------------------- #
# Tool definitions (Ollama / OpenAI function-calling format)
# ---------------------------------------------------------------------- #


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


TOOLS: list[dict] = [
    _tool(
        "create_file",
        "Create a new file with the given content. Parent directories are created "
        "automatically. Content must be the complete file content.",
        {
            "path": {"type": "string", "description": "Project-relative file path"},
            "content": {"type": "string", "description": "Complete file content"},
        },
        ["path", "content"],
    ),
    _tool(
        "edit_file",
        "Overwrite an existing file with new content. Content must be the COMPLETE "
        "new file content, not a diff or fragment.",
        {
            "path": {"type": "string", "description": "Project-relative file path"},
            "content": {"type": "string", "description": "Complete new file content"},
        },
        ["path", "content"],
    ),
    _tool(
        "delete_file",
        "Delete a file or directory from the project.",
        {"path": {"type": "string", "description": "Project-relative path to delete"}},
        ["path"],
    ),
    _tool(
        "move_file",
        "Move or rename a file or directory.",
        {
            "path": {"type": "string", "description": "Current project-relative path"},
            "dest": {"type": "string", "description": "New project-relative path"},
        },
        ["path", "dest"],
    ),
    _tool(
        "create_directory",
        "Create a directory (with parents) inside the project.",
        {"path": {"type": "string", "description": "Project-relative directory path"}},
        ["path"],
    ),
    _tool(
        "run_command",
        "Run a shell command in the project root (60s timeout). Returns stdout, "
        "stderr and the exit code.",
        {"command": {"type": "string", "description": "Shell command to run"}},
        ["command"],
    ),
    _tool(
        "read_file",
        "Read and return the content of a file in the project.",
        {"path": {"type": "string", "description": "Project-relative file path"}},
        ["path"],
    ),
    _tool(
        "search_code",
        "Search all project text files for a string (case-insensitive). Returns "
        "matching lines as path:line: text.",
        {"query": {"type": "string", "description": "Text to search for"}},
        ["query"],
    ),
]

# Tools that modify the filesystem; excluded in plan mode.
WRITE_TOOL_NAMES = {
    "create_file", "edit_file", "delete_file", "move_file",
    "create_directory", "run_command",
}


def tools_for_mode(mode: str) -> list[dict]:
    """Full toolset in build mode; read-only tools in plan mode."""
    if mode == "plan":
        return [t for t in TOOLS if t["function"]["name"] not in WRITE_TOOL_NAMES]
    return TOOLS


# ---------------------------------------------------------------------- #
# Capability detection
# ---------------------------------------------------------------------- #

TOOL_CAPABLE_MODELS = (
    "qwen2.5-coder",
    "qwen2.5",
    "qwen3",
    "llama3.1",
    "llama3.2",
    "llama3.3",
    "mistral-nemo",
    "deepseek-coder-v2",
    "hermes3",
)


def model_supports_tools(model_name: str) -> bool:
    """True if the model family is known to support native tool calling."""
    if not model_name:
        return False
    name = model_name.lower()
    return any(family in name for family in TOOL_CAPABLE_MODELS)


# ---------------------------------------------------------------------- #
# Action parsing (fallback path for models without native tool calling)
# ---------------------------------------------------------------------- #

VALID_ACTION_TYPES = {"create", "edit", "delete", "move", "mkdir", "shell", "read", "search"}

_ACTION_BLOCK_RE = re.compile(r"```action\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def _normalize_action(data: dict) -> dict | None:
    """Validate/normalize one parsed object into an action dict, or None."""
    if not isinstance(data, dict):
        return None
    # Tool-call-shaped JSON written as plain text by the model:
    # {"name": "create_file", "arguments": {"path": ..., "content": ...}}
    # (qwen2.5-coder does this instead of using Ollama's native tool_calls).
    if "type" not in data and "action" not in data and data.get("name"):
        args = data.get("arguments", data.get("parameters", {}))
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        if isinstance(args, dict):
            data = {"type": str(data["name"]), **args}
    kind = (data.get("type") or data.get("action") or "").strip().lower()
    aliases = {
        "create_file": "create", "edit_file": "edit", "write": "create",
        "delete_file": "delete", "move_file": "move", "rename": "move",
        "create_directory": "mkdir", "run_command": "shell", "run": "shell",
        "command": "shell", "read_file": "read", "search_code": "search",
    }
    kind = aliases.get(kind, kind)
    if kind not in VALID_ACTION_TYPES:
        return None
    action: dict = {"type": kind}
    for key in ("path", "content", "dest", "command", "query", "description"):
        if key in data and data[key] is not None:
            action[key] = data[key]
    # `file`/`filename`/`to` are common aliases models invent
    if "path" not in action:
        for alt in ("file", "filename", "filepath", "target"):
            if data.get(alt):
                action["path"] = data[alt]
                break
    if "dest" not in action and data.get("to"):
        action["dest"] = data["to"]
    if kind in ("create", "edit", "delete", "move", "mkdir", "read") and not action.get("path"):
        return None
    if kind == "shell" and not action.get("command"):
        return None
    if kind == "search" and not action.get("query"):
        return None
    return action


def _try_parse_objects(text: str) -> list[dict]:
    """Parse text that may hold one JSON object, a JSON list, or several objects."""
    text = text.strip()
    if not text:
        return []
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
        if isinstance(data, dict):
            return [data]
    except json.JSONDecodeError:
        pass
    # Several concatenated objects: scan with raw_decode.
    objects: list[dict] = []
    decoder = json.JSONDecoder()
    index = 0
    while index < len(text):
        brace = text.find("{", index)
        if brace == -1:
            break
        try:
            obj, end = decoder.raw_decode(text, brace)
        except json.JSONDecodeError:
            index = brace + 1
            continue
        if isinstance(obj, dict):
            objects.append(obj)
        index = end
    return objects


def parse_action_blocks(text: str) -> list[dict]:
    """Extract action dicts from model output.

    Priority: ```action blocks, then ```json blocks, then bare JSON objects
    found anywhere in the text. Only well-formed actions are returned.
    """
    if not text:
        return []

    actions: list[dict] = []

    action_blocks = _ACTION_BLOCK_RE.findall(text)
    for block in action_blocks:
        for obj in _try_parse_objects(block):
            normalized = _normalize_action(obj)
            if normalized:
                actions.append(normalized)
    if actions:
        return actions

    for block in _JSON_BLOCK_RE.findall(text):
        for obj in _try_parse_objects(block):
            normalized = _normalize_action(obj)
            if normalized:
                actions.append(normalized)
    if actions:
        return actions

    # Last resort: bare JSON objects in the raw text (outside code fences).
    stripped = _ACTION_BLOCK_RE.sub("", _JSON_BLOCK_RE.sub("", text))
    if "{" in stripped:
        for obj in _try_parse_objects(stripped):
            normalized = _normalize_action(obj)
            if normalized:
                actions.append(normalized)
    return actions


# ---------------------------------------------------------------------- #
# Tool call -> action mapping
# ---------------------------------------------------------------------- #

_TOOL_TO_TYPE = {
    "create_file": "create",
    "edit_file": "edit",
    "delete_file": "delete",
    "move_file": "move",
    "create_directory": "mkdir",
    "run_command": "shell",
    "read_file": "read",
    "search_code": "search",
}


def tool_call_to_action(name: str, args: dict) -> dict | None:
    """Map a native tool call to an action dict, or None if unknown/invalid."""
    kind = _TOOL_TO_TYPE.get(name)
    if kind is None:
        return None
    if not isinstance(args, dict):
        args = {}
    action = {"type": kind}
    for key in ("path", "content", "dest", "command", "query", "description"):
        if key in args and args[key] is not None:
            action[key] = args[key]
    return _normalize_action(action)
