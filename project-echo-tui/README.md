# Project Echo

Local AI coding assistant for the terminal. Works completely offline with any local model.

```
◈ PROJECT ECHO   ▶ BUILD   Model: qwen2.5-coder:14b   ●   my-project
CTX  No file context — use /tree or /read <path>      Ctrl+S: model  Ctrl+M: mode
────────────────────────────────────────────────────────────────────────────────

  Echo  I'll create tasks.py with the TaskManager class...

  ┌─ ✚ CREATE  tasks.py ────────────────────────────────────────────────────┐
  │  Creates task management with add, list, complete, delete methods        │
  │  import json                                                              │
  │  from pathlib import Path                                                 │
  │  class TaskManager:...                                                    │
  │  [✓ Apply]  [✕ Reject]  [✎ Edit]                                        │
  └───────────────────────────────────────────────────────────────────────────┘

> Message Echo...                                                    [Send ↑]
────────────────────────────────────────────────────────────────────────────────
^C Quit   ^M Plan/Build   ^L Clear   ^T Tree   ^S Model   ^P Preferences
```

---

## Requirements

- Python 3.10+
- Ollama, LM Studio, or any OpenAI-compatible local model server

## Installation

```bash
cd project-echo-tui
pip install -r requirements.txt
pip install -e .
```

After installing, the `echo` command is available globally.

## Usage

```bash
# Navigate to your project
cd my-project

# Launch Project Echo
echo

# Or specify a path
echo /path/to/project
```

## First use

1. Make sure your model server is running (e.g. `ollama serve`)
2. Run `echo` in your project folder
3. Press `Ctrl+S` to select a model if none is selected
4. Start chatting

## Configuration

All config is stored in `~/.echo/`:

| File | Purpose |
|---|---|
| `~/.echo/config.json` | Provider settings, model, preferences |
| `~/.echo/preferences.md` | Your global coding style and rules |
| `~/.echo/global.db` | Cross-project session history |

Per-project memory is stored in `<project>/.echo/`:

| File | Purpose |
|---|---|
| `.echo/memory.md` | Project description, stack, goals — edit freely |
| `.echo/memory.db` | Conversation history, file index, action log |

## Keyboard shortcuts

| Key | Action |
|---|---|
| `Enter` | Send message |
| `Ctrl+M` | Toggle Plan/Build mode |
| `Ctrl+S` | Open model selector |
| `Ctrl+L` | Clear chat history |
| `Ctrl+T` | Show project tree |
| `Ctrl+P` | Show preferences path |
| `Ctrl+C` | Quit |

## Slash commands

| Command | Description |
|---|---|
| `/help` | Show all commands |
| `/tree` | Show project directory tree |
| `/read <path>` | Read and display a file |
| `/search <text>` | Search for text across all files |
| `/run <command>` | Execute a shell command |
| `/clear` | Clear conversation history |
| `/memory` | Show project memory status |
| `/plan` | Switch to Plan mode (analysis only) |
| `/build` | Switch to Build mode (file access) |
| `/models` | List available models |
| `/model <name>` | Switch model (preserves history) |
| `/undo` | Undo last file action |
| `/prefs` | Show preferences file path |

## Supported providers

| Provider | Default port | Notes |
|---|---|---|
| Ollama | 11434 | Native API + tool calling |
| LM Studio | 1234 | OpenAI-compatible |
| llama.cpp server | 8080 | OpenAI-compatible |
| Any OpenAI-compat | configurable | Custom endpoint |

## Model compatibility

Models with ⚡ in the selector support **native tool calling** — the most reliable way to create and edit files. Models without it use action blocks (fallback mode, still works).

**Recommended models for 16GB RAM:**
- `qwen2.5-coder:14b` — best balance, ~9GB RAM, tool calling ✓
- `qwen2.5-coder:7b` — faster, ~4.5GB RAM, tool calling ✓
- `deepseek-coder-v2:16b` — strong alternative, ~10GB RAM, tool calling ✓

## Troubleshooting

**"Cannot reach model server"**
Make sure Ollama is running: `ollama serve`

**Model not creating files**
- Check mode is `▶ BUILD` (not `◎ PLAN`)
- If using a small model without tool calling, try `/model qwen2.5-coder:14b`

**Slow responses**
Normal for large models on CPU. Echo has no timeout — the response will arrive.

**Config reset**
Delete `~/.echo/config.json` to reset all settings.
