"""Configuration for Project Echo, persisted at ~/.echo/config.json."""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".echo"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULTS: dict = {
    "provider": "ollama",
    "base_url": "http://localhost",
    "port": 11434,
    "model": "",
    "api_key": "",
    "confirm_actions": True,
    "streaming": True,
    "auto_close_session": True,
    "include_context_default": True,
    "max_history": 20,
    "mode": "build",
    "theme": "dark",
}

# Settings the user can change with /config, and their types/valid values.
USER_SETTINGS: dict = {
    "confirm_actions": bool,
    "streaming": bool,
    "auto_close_session": bool,
    "include_context_default": bool,
    "max_history": int,
    "mode": ("build", "plan"),
    "theme": ("dark",),
}


def load() -> dict:
    """Read ~/.echo/config.json, falling back to defaults for missing keys."""
    cfg = dict(DEFAULTS)
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update(data)
    except (OSError, json.JSONDecodeError):
        pass  # corrupted/unreadable config: keep defaults
    return cfg


def save(data: dict) -> None:
    """Write the config to ~/.echo/config.json (merged over defaults)."""
    cfg = dict(DEFAULTS)
    cfg.update(data or {})
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def get_provider(cfg: dict):
    """Return the provider instance described by the config dict."""
    from echo.core.providers import OllamaProvider, OpenAICompatProvider

    name = (cfg.get("provider") or "ollama").lower()
    base_url = cfg.get("base_url") or "http://localhost"
    port = cfg.get("port")

    if name in ("openai", "openai-compat", "openai_compat", "lmstudio", "llamacpp"):
        return OpenAICompatProvider(
            base_url=base_url, port=port, api_key=cfg.get("api_key", "")
        )
    return OllamaProvider(base_url=base_url, port=port)
