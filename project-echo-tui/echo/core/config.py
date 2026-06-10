"""
Config manager — persists provider settings to ~/.echo/config.json
"""
import json
from pathlib import Path

CONFIG_PATH = Path.home() / ".echo" / "config.json"

DEFAULTS = {
    "provider":       "ollama",
    "base_url":       "http://localhost",
    "port":           11434,
    "model":          "",
    "confirm_actions": True,
    "streaming":       True,
    "mode":            "build",
    "max_history":     20,
}


def load() -> dict:
    CONFIG_PATH.parent.mkdir(exist_ok=True)
    if CONFIG_PATH.exists():
        try:
            return {**DEFAULTS, **json.loads(CONFIG_PATH.read_text())}
        except Exception:
            pass
    return DEFAULTS.copy()


def save(data: dict) -> None:
    CONFIG_PATH.parent.mkdir(exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2))


def get_provider(cfg: dict):
    from echo.core.providers import OllamaProvider, OpenAICompatProvider
    match cfg.get("provider", "ollama"):
        case "ollama":
            return OllamaProvider(cfg["base_url"], cfg["port"])
        case _:
            return OpenAICompatProvider(cfg["base_url"], cfg["port"])
