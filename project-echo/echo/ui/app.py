"""Project Echo - Textual terminal UI.

Layout: 1-line top bar | scrollable chat | 3-line input bar | footer.
Streaming runs in async workers (no threads, no call_from_thread).
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, OptionList, Static, TextArea
from textual.widgets.option_list import Option

from echo import __app_name__, __version__
from echo.core import config as config_mod
from echo.core.executor import ActionError, Executor
from echo.core.installer import (
    InstallError,
    collect_sources,
    install_skills_from_github,
)
from echo.core.providers import ProviderError
from echo.memory.manager import (
    GLOBAL_SKILLS_DIR,
    GlobalMemory,
    ProjectMemory,
    parse_skill_frontmatter,
)
from echo.tools.definitions import (
    TOOLS,
    model_supports_tools,
    parse_action_blocks,
    tool_call_to_action,
)

# Palette
BG = "#0d0d0d"
CYAN = "#00e5ff"
PURPLE = "#b06fff"
GREEN = "#00e5aa"
RED = "#ff5566"
DIM = "#777777"

ACTION_LABELS = {
    "create": ("CREATE", GREEN),
    "edit": ("EDIT", CYAN),
    "delete": ("DELETE", RED),
    "move": ("MOVE", PURPLE),
    "mkdir": ("MKDIR", GREEN),
    "shell": ("SHELL", PURPLE),
    "read": ("READ", CYAN),
    "search": ("SEARCH", CYAN),
}

SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# Chat spinner labels per action type ({}: path / command / query).
SPINNER_VERBS = {
    "read": "Reading {}...",
    "create": "Creating {}...",
    "edit": "Editing {}...",
    "delete": "Deleting {}...",
    "move": "Moving {}...",
    "mkdir": "Creating directory {}...",
    "shell": "Running: {}...",
    "search": "Searching for '{}'...",
}

# Short top-bar status per action type.
STATUS_VERBS = {
    "read": "reading file...",
    "create": "creating file...",
    "edit": "editing file...",
    "delete": "deleting file...",
    "move": "moving file...",
    "mkdir": "creating directory...",
    "shell": "running command...",
    "search": "searching...",
}


def _action_target(action: dict) -> str:
    return str(
        action.get("path") or action.get("command") or action.get("query") or ""
    )

HELP_TEXT = """\
Slash commands:
  /help               this help
  /tree               show project tree
  /read <path>        show a file
  /search <text>      search project files
  /run <cmd>          run a shell command (60s timeout)
  /clear              clear conversation
  /memory             show project memory (facts, recent actions)
  /plan  /build       switch mode
  /models             list available models
  /model <name>       switch model (history is preserved)
  /skills             list available skills (global + project)
  /skills active      list currently active skills
  /skill <name>       activate a skill
  /skill off [name]   deactivate all skills, or one by name
  /skill save [--global] <name>   create a skill from this conversation
  /skill install <github-url> [--project]   install skills from GitHub
  /skill uninstall <name>                   remove an installed skill
  /skill update                             re-download installed skills
  /config             show all settings
  /config <key>       show one setting
  /config <key> <value>   change a setting (saved immediately)
  /undo               undo the last applied file action
  /prefs              show global preferences (~/.echo/preferences.md)

Keys: Ctrl+M mode | Ctrl+S model picker | Ctrl+A confirm toggle | Ctrl+L clear
      Ctrl+T tree | Ctrl+C quit
"""


def _extract_skill_md(text: str, name: str) -> str:
    """Pull a SKILL.md out of a model response: prefer a fenced block with
    frontmatter, then bare frontmatter text; otherwise wrap the whole answer."""
    import re

    # Model may wrap the file in a create action despite instructions:
    # unwrap {"type": "create", "content": "---\n..."} first.
    for action in parse_action_blocks(text):
        content = str(action.get("content", ""))
        if content.lstrip().startswith("---"):
            text = content
            break

    for match in re.findall(r"```(?:markdown|md|yaml)?\s*\n(.*?)```", text, re.DOTALL):
        if match.lstrip().startswith("---"):
            text = match
            break
    text = text.strip()
    # A leading ```yaml fence with name/description is frontmatter in disguise.
    fenced_meta = re.match(r"^```(?:yaml|yml)\s*\n(.*?)```\s*\n?(.*)$", text, re.DOTALL)
    if fenced_meta and "name:" in fenced_meta.group(1):
        text = f"---\n{fenced_meta.group(1).strip()}\n---\n\n{fenced_meta.group(2).strip()}"
    if text.startswith("---") and parse_skill_frontmatter(text).get("name"):
        return text + ("\n" if not text.endswith("\n") else "")
    description = "Generated from an Echo conversation"
    return (
        f"---\nname: {name}\ndescription: {description}\n---\n\n{text}\n"
    )


# ---------------------------------------------------------------------- #
# Widgets
# ---------------------------------------------------------------------- #


class ChatMessage(Vertical):
    """A single chat entry: a small label line plus the message body."""

    def __init__(self, label: str, label_class: str, text: str = ""):
        super().__init__(classes="chat-message")
        self._label = label
        self._label_class = label_class
        self._text = text

    def compose(self) -> ComposeResult:
        yield Static(self._label, classes=f"msg-label {self._label_class}")
        yield Static(Text(self._text), classes="msg-body")

    def set_text(self, text: str) -> None:
        self._text = text
        try:
            self.query_one(".msg-body", Static).update(Text(text))
        except NoMatches:
            pass  # not composed yet; compose() renders self._text on mount

    @property
    def text(self) -> str:
        return self._text


class ActionCard(Vertical):
    """Proposed action with Apply / Reject / Edit buttons (source: tool|block)."""

    PREVIEW_LINES = 12

    def __init__(self, action: dict, source: str = "block"):
        super().__init__(classes="action-card")
        self.action = action
        self.source = source
        self.resolved = False
        self._editing = False

    def compose(self) -> ComposeResult:
        kind = self.action.get("type", "?")
        label, color = ACTION_LABELS.get(kind, (kind.upper(), DIM))

        head = Text()
        head.append(f" {label} ", style=f"bold {BG} on {color}")
        target = self.action.get("path") or self.action.get("command") \
            or self.action.get("query") or ""
        if target:
            head.append("  ")
            head.append(str(target), style=f"bold {CYAN}")
        if kind == "move" and self.action.get("dest"):
            head.append(f"  ->  {self.action['dest']}", style=f"bold {CYAN}")
        yield Static(head, classes="card-head")

        description = self.action.get("description", "")
        if description:
            yield Static(Text(str(description), style=DIM), classes="card-desc")

        content = self.action.get("content", "")
        if content:
            lines = str(content).splitlines()
            preview = "\n".join(lines[: self.PREVIEW_LINES])
            if len(lines) > self.PREVIEW_LINES:
                preview += f"\n... (+{len(lines) - self.PREVIEW_LINES} more lines)"
            yield Static(Text(preview, style="#cccccc"), classes="card-preview")
            editor = TextArea(str(content), classes="card-editor")
            editor.display = False
            yield editor

        with Horizontal(classes="card-buttons"):
            yield Button("Apply", variant="success", classes="btn-apply")
            yield Button("Reject", variant="error", classes="btn-reject")
            if content:
                yield Button("Edit", variant="default", classes="btn-edit")

    def toggle_edit(self) -> None:
        editors = self.query(".card-editor")
        previews = self.query(".card-preview")
        if not editors:
            return
        self._editing = not self._editing
        editors.first().display = self._editing
        if previews:
            previews.first().display = not self._editing
        if self._editing:
            editors.first().focus()

    def final_action(self) -> dict:
        """The action to execute, with any edits made in the TextArea."""
        action = dict(self.action)
        editors = self.query(".card-editor")
        if editors and self._editing:
            action["content"] = editors.first().text
        elif editors:
            action["content"] = editors.first().text  # keep edits even if toggled back
        return action

    def mark_resolved(self, verdict: str) -> None:
        self.resolved = True
        for button in self.query(Button):
            button.disabled = True
        style = GREEN if verdict == "applied" else RED
        self.mount(Static(Text(f"✓ {verdict}" if verdict == "applied" else f"✗ {verdict}",
                               style=f"bold {style}"), classes="card-verdict"))


class SpinnerLine(Static):
    """One-line animated spinner with a label, e.g. '⠋ Thinking...'.
    Self-animates at 100 ms; never blocks input."""

    def __init__(self, label: str):
        super().__init__(classes="spinner-line")
        self.label = label
        self._frame = 0
        self._update_text()

    def on_mount(self) -> None:
        self.set_interval(0.1, self._tick)

    def _tick(self) -> None:
        self._frame = (self._frame + 1) % len(SPINNER_FRAMES)
        self._update_text()

    def _update_text(self) -> None:
        self.update(Text(f"{SPINNER_FRAMES[self._frame]} {self.label}", style=CYAN))

    def set_label(self, label: str) -> None:
        self.label = label
        self._update_text()


class ConfirmScreen(ModalScreen[bool]):
    """Small yes/no confirmation dialog."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(Text(self.message), id="confirm-message")
            with Horizontal(id="confirm-buttons"):
                yield Button("Yes", variant="error", id="confirm-yes")
                yield Button("Cancel", variant="default", id="confirm-no")

    @on(Button.Pressed, "#confirm-yes")
    def _yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#confirm-no")
    def _no(self) -> None:
        self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)


class ModelPickerScreen(ModalScreen[str | None]):
    """Overlay listing available models; ⚡ marks tool-capable ones."""

    BINDINGS = [Binding("escape", "dismiss_picker", "Close")]

    def __init__(self, models: list[str], current: str):
        super().__init__()
        self.models = models
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-box"):
            yield Static(
                Text(" Select model    ⚡ = native tool calling    Esc closes ",
                     style=f"bold {BG} on {CYAN}"),
                id="picker-title",
            )
            option_list = OptionList(id="picker-list")
            yield option_list

    def on_mount(self) -> None:
        option_list = self.query_one("#picker-list", OptionList)
        if not self.models:
            option_list.add_option(Option("(no models found - is the server running?)", disabled=True))
            return
        for name in self.models:
            bolt = "⚡ " if model_supports_tools(name) else "   "
            marker = "  ←" if name == self.current else ""
            prompt = Text()
            prompt.append(bolt, style=GREEN)
            prompt.append(name, style="bold" if name == self.current else "")
            if marker:
                prompt.append(marker, style=DIM)
            option_list.add_option(Option(prompt, id=name))
        option_list.focus()

    @on(OptionList.OptionSelected, "#picker-list")
    def _selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_dismiss_picker(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------- #
# App
# ---------------------------------------------------------------------- #


class EchoApp(App):
    TITLE = __app_name__

    BINDINGS = [
        Binding("ctrl+m", "toggle_mode", "Mode"),
        Binding("ctrl+s", "pick_model", "Model"),
        Binding("ctrl+a", "toggle_confirm", "Confirm", priority=True),
        Binding("ctrl+l", "clear_chat", "Clear"),
        Binding("ctrl+t", "show_tree", "Tree"),
        Binding("ctrl+c", "quit", "Quit", priority=True),
    ]

    CSS = f"""
    Screen {{
        background: {BG};
    }}
    #topbar {{
        height: 1;
        background: #151522;
        padding: 0 1;
    }}
    #chat {{
        background: {BG};
        padding: 0 1;
    }}
    .chat-message {{
        height: auto;
        margin: 1 0 0 0;
    }}
    .msg-label {{
        height: 1;
        text-style: bold;
    }}
    .label-you {{ color: {GREEN}; }}
    .label-echo {{ color: {CYAN}; }}
    .label-system {{ color: {DIM}; }}
    .msg-body {{
        height: auto;
        color: #e8e8e8;
        padding: 0 0 0 2;
    }}
    .action-card {{
        height: auto;
        margin: 1 2 0 2;
        padding: 0 1;
        border: round {PURPLE};
        background: #131320;
    }}
    .card-head {{ height: 1; margin: 0 0 0 0; }}
    .card-desc {{ height: auto; }}
    .card-preview {{
        height: auto;
        max-height: 14;
        margin: 0 0 0 1;
        background: #0a0a14;
        padding: 0 1;
    }}
    .card-editor {{
        height: 14;
        margin: 0 0 0 1;
    }}
    .card-buttons {{
        height: 3;
        align-horizontal: left;
    }}
    .card-buttons Button {{
        margin: 0 1 0 0;
        min-width: 10;
    }}
    .card-verdict {{ height: 1; }}
    .spinner-line {{
        height: 1;
        margin: 1 0 0 0;
    }}
    .result-line {{
        height: auto;
        margin: 0 0 0 2;
    }}
    ConfirmScreen {{
        align: center middle;
    }}
    #confirm-box {{
        width: 60;
        height: auto;
        border: round {RED};
        background: #131320;
        padding: 1;
    }}
    #confirm-message {{ height: auto; }}
    #confirm-buttons {{
        height: 3;
        align-horizontal: right;
    }}
    #confirm-buttons Button {{ margin: 0 0 0 1; min-width: 10; }}
    #input-bar {{
        height: 3;
        padding: 0 1;
        background: #151522;
    }}
    #prompt-input {{
        background: {BG};
        border: round {CYAN};
        color: #e8e8e8;
    }}
    #prompt-input:focus {{
        border: round {GREEN};
    }}
    ModelPickerScreen {{
        align: center middle;
    }}
    #picker-box {{
        width: 64;
        max-height: 22;
        height: auto;
        border: round {CYAN};
        background: #131320;
    }}
    #picker-title {{ height: 1; }}
    #picker-list {{
        height: auto;
        max-height: 18;
        background: #131320;
    }}
    Footer {{
        background: #151522;
    }}
    """

    def __init__(self, project_root: str | Path | None = None):
        super().__init__()
        self.project_root = Path(project_root or Path.cwd()).resolve()
        self.cfg = config_mod.load()
        self.provider = config_mod.get_provider(self.cfg)
        self.model: str = self.cfg.get("model", "")
        self.mode: str = self.cfg.get("mode") if self.cfg.get("mode") in ("build", "plan") else "build"
        self.status_label: str = ""  # "" = idle; otherwise top-bar spinner text
        self._spinner_frame = 0
        self._spinner: SpinnerLine | None = None
        self.connected: bool = False
        self.busy: bool = False
        self.history: list[dict] = []
        self.executor = Executor(self.project_root)
        self.pmem = ProjectMemory(self.project_root)
        self.gmem = GlobalMemory()
        self._pending_tool_cards = 0
        self._tool_results: list[dict] = []
        self._tool_call_seq = 0
        self.active_skills: set[str] = set()
        self.debug_log = self._setup_debug_log()

    def _setup_debug_log(self) -> logging.Logger:
        """File logger at .echo/debug.log (prints would corrupt the TUI)."""
        logger = logging.getLogger("echo.debug")
        logger.setLevel(logging.DEBUG)
        if not logger.handlers:
            handler = logging.FileHandler(
                self.project_root / ".echo" / "debug.log", encoding="utf-8"
            )
            handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            logger.addHandler(handler)
        return logger

    # ------------------------------------------------------------------ #
    # Layout
    # ------------------------------------------------------------------ #

    def compose(self) -> ComposeResult:
        yield Static(id="topbar")
        yield VerticalScroll(id="chat")
        with Horizontal(id="input-bar"):
            yield Input(
                placeholder="Message Echo...  ( / for commands )",
                id="prompt-input",
            )
        yield Footer()

    @property
    def chat(self) -> VerticalScroll:
        return self.query_one("#chat", VerticalScroll)

    def on_unmount(self) -> None:
        """Summarize the session, then release file handles (Windows locks them)."""
        if self.cfg.get("auto_close_session", True):
            user_messages = sum(1 for m in self.history if m.get("role") == "user")
            actions = len(self.pmem.get_recent_actions(limit=100))
            self.gmem.log_session(
                str(self.project_root),
                f"session ended: {user_messages} user messages, "
                f"{actions} actions logged, mode={self.mode}",
            )
        for handler in list(self.debug_log.handlers):
            handler.close()
            self.debug_log.removeHandler(handler)
        self.pmem.close()
        self.gmem.close()

    def on_mount(self) -> None:
        self.set_interval(0.1, self._spin_tick)
        self._refresh_topbar()
        self.query_one("#prompt-input", Input).focus()
        self.add_system(f"{__app_name__} v{__version__} - project: {self.project_root.name}")
        tree = self.pmem.build_tree(max_depth=3)
        files = self.pmem.count_files()
        self.add_system(f"{tree}\n\n{files} files indexed. /help for commands.")
        self.gmem.log_session(str(self.project_root), "session started")
        self.run_worker(self._startup_check(), exclusive=False)

    async def _startup_check(self) -> None:
        self.connected = await self.provider.health()
        if self.connected:
            try:
                models = await self.provider.list_models()
            except ProviderError:
                models = []
            if not self.model and models:
                self.model = models[0]
                self.cfg["model"] = self.model
                config_mod.save(self.cfg)
            if self.model:
                bolt = "⚡ tool calling" if model_supports_tools(self.model) \
                    else "no native tools (action-block fallback)"
                self.add_system(f"Connected. Model: {self.model} ({bolt})")
            else:
                self.add_system("Connected, but no models available. Pull one with: ollama pull qwen2.5-coder")
        else:
            self.add_system(
                f"⚠ Could not reach {self.provider.name} server. "
                "Start it and press Ctrl+S to pick a model."
            )
        self._refresh_topbar()

    # ------------------------------------------------------------------ #
    # Top bar
    # ------------------------------------------------------------------ #

    def _refresh_topbar(self) -> None:
        bar = Text()
        bar.append(" ◤ ECHO ◢ ", style=f"bold {BG} on {CYAN}")
        bar.append("  ")
        if self.mode == "build":
            bar.append(" ▶ BUILD ", style=f"bold {BG} on {GREEN}")
        else:
            bar.append(" ◎ PLAN ", style=f"bold {BG} on {PURPLE}")
        bar.append("  ")
        if self.model:
            prefix = "⚡ " if model_supports_tools(self.model) else ""
            bar.append(f"{prefix}{self.model}", style=f"bold {CYAN}")
        else:
            bar.append("no model (Ctrl+S)", style=DIM)
        if self.active_skills:
            count = len(self.active_skills)
            bar.append("  ")
            bar.append(
                f" ✦ {count} skill{'s' if count != 1 else ''} ",
                style=f"bold {BG} on {PURPLE}",
            )
        if not self.cfg.get("confirm_actions", True):
            bar.append("  ")
            bar.append("[auto]", style="bold #ffcc00")
        bar.append("   ")
        bar.append(self.project_root.name, style=PURPLE)
        bar.append("   ")
        if self.status_label:
            bar.append(
                f"{SPINNER_FRAMES[self._spinner_frame]} {self.status_label}",
                style=f"bold {CYAN}",
            )
        else:
            bar.append("●", style=GREEN if self.connected else RED)
        self.query_one("#topbar", Static).update(bar)

    # ------------------------------------------------------------------ #
    # Spinners / status
    # ------------------------------------------------------------------ #

    def _spin_tick(self) -> None:
        if self.status_label:
            self._spinner_frame = (self._spinner_frame + 1) % len(SPINNER_FRAMES)
            self._refresh_topbar()

    def _set_status(self, label: str = "") -> None:
        self.status_label = label
        self._refresh_topbar()

    def _show_spinner(self, label: str) -> None:
        if self._spinner is not None:
            self._spinner.set_label(label)
            return
        self._spinner = SpinnerLine(label)
        self.chat.mount(self._spinner)
        self.chat.scroll_end(animate=False)

    def _hide_spinner(self) -> None:
        if self._spinner is not None:
            self._spinner.remove()
            self._spinner = None

    def _add_result_line(self, result: str) -> None:
        """✓/✗ line shown in place of a card when actions auto-apply."""
        ok = not result.startswith("Error:")
        text = f"✓ {result}" if ok else f"✗ Failed: {result[len('Error: '):]}"
        if len(text) > 1500:
            text = text[:1500] + "\n... (truncated)"
        self.chat.mount(
            Static(Text(text, style=GREEN if ok else RED), classes="result-line")
        )
        self.chat.scroll_end(animate=False)

    # ------------------------------------------------------------------ #
    # Chat helpers
    # ------------------------------------------------------------------ #

    def add_message(self, label: str, label_class: str, text: str) -> ChatMessage:
        message = ChatMessage(label, label_class, text)
        self.chat.mount(message)
        self.chat.scroll_end(animate=False)
        return message

    def add_system(self, text: str) -> ChatMessage:
        return self.add_message("·", "label-system", text)

    def add_you(self, text: str) -> ChatMessage:
        return self.add_message("You", "label-you", text)

    def add_echo(self, text: str = "") -> ChatMessage:
        return self.add_message("Echo", "label-echo", text)

    # ------------------------------------------------------------------ #
    # Input handling
    # ------------------------------------------------------------------ #

    @on(Input.Submitted, "#prompt-input")
    def _on_submit(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        if text.startswith("/"):
            self.handle_command(text)
            return
        if self.busy:
            self.add_system("Echo is still responding - wait for it to finish.")
            return
        if not self.model:
            self.add_system("No model selected. Press Ctrl+S or use /model <name>.")
            return
        self.add_you(text)
        self.history.append({"role": "user", "content": text})
        self.pmem.add_message("user", text)
        self.run_worker(self._generate(), exclusive=True, group="generate")

    # ------------------------------------------------------------------ #
    # Generation / streaming
    # ------------------------------------------------------------------ #

    def _build_messages(self) -> list[dict]:
        if self.cfg.get("include_context_default", True):
            system_prompt = self.pmem.build_system_prompt(
                global_prefs=self.gmem.read_md(), mode=self.mode
            )
        else:
            system_prompt = (
                f"You are Echo, a coding assistant working in the project "
                f"'{self.project_root.name}'. Be concise and practical."
            )
        if self.active_skills:
            skills_text = self.pmem.load_active_skills(sorted(self.active_skills))
            if skills_text:
                system_prompt = skills_text + "\n\n" + system_prompt
        try:
            limit = int(self.cfg.get("max_history", 20))
        except (TypeError, ValueError):
            limit = 20
        history = self.history[-limit:] if limit > 0 else list(self.history)
        return [{"role": "system", "content": system_prompt}] + history

    def _tools_for_request(self) -> list[dict] | None:
        """Tools for the next API call: none at all in plan mode."""
        if self.mode == "plan":
            return None
        return TOOLS if model_supports_tools(self.model) else None

    async def _generate(self) -> None:
        self.busy = True
        supports = model_supports_tools(self.model)
        tools = self._tools_for_request()
        self.debug_log.debug(
            "[generate] model=%s mode=%s supports_tools=%s sending_tools=%s",
            self.model, self.mode, supports,
            [t["function"]["name"] for t in tools] if tools else "NONE",
        )

        streaming_on = bool(self.cfg.get("streaming", True))
        self._set_status("generating...")
        self._show_spinner("Thinking...")

        message_widget: ChatMessage | None = None
        full_text = ""
        tool_calls: list[dict] = []

        try:
            async for chunk in self.provider.stream(
                self._build_messages(), self.model, tools
            ):
                if isinstance(chunk, str):
                    full_text += chunk
                    if streaming_on:
                        if message_widget is None:
                            # First token: spinner goes away, message appears.
                            self._hide_spinner()
                            self._set_status("streaming...")
                            message_widget = self.add_echo("")
                        message_widget.set_text(full_text)
                        self.chat.scroll_end(animate=False)
                elif isinstance(chunk, dict) and "tool_call" in chunk:
                    self.debug_log.debug("[stream] tool_call received: %s",
                                     json.dumps(chunk["tool_call"])[:300])
                    tool_calls.append(chunk["tool_call"])
                    action = tool_call_to_action(
                        chunk["tool_call"].get("name", ""),
                        chunk["tool_call"].get("arguments", {}),
                    )
                    if action:
                        target = _action_target(action)
                        self._show_spinner(SPINNER_VERBS[action["type"]].format(target))
                        self._set_status(STATUS_VERBS[action["type"]])
            self.connected = True
        except ProviderError as exc:
            self.connected = False
            self._hide_spinner()
            if full_text and message_widget is None:
                self.add_echo(full_text)
            self.add_system(f"⚠ {exc}")
            self.busy = False
            self._set_status()
            return

        self._hide_spinner()
        if full_text and message_widget is None:
            # streaming=false: show the complete response at once.
            self.add_echo(full_text)
        elif not full_text and not tool_calls:
            self.add_echo("(empty response)")

        # Record assistant turn (with tool calls if any) in history + memory.
        assistant_message: dict = {"role": "assistant", "content": full_text}
        if tool_calls:
            assistant_message["tool_calls"] = [
                self._format_tool_call(tc, i) for i, tc in enumerate(tool_calls)
            ]
        self.history.append(assistant_message)
        if full_text:
            self.pmem.add_message("assistant", full_text)
        self.pmem.save_snapshot()

        self.debug_log.debug(
            "[generate] stream finished: %d chars text, %d native tool_calls",
            len(full_text), len(tool_calls),
        )

        if tool_calls:
            self._handle_tool_calls(tool_calls)
        elif full_text and self.mode == "build":
            # Fallback even for tool-capable models: qwen2.5-coder often writes
            # the tool call as plain JSON text instead of using native tool_calls.
            actions = parse_action_blocks(full_text)
            self.debug_log.debug("[parse] parse_action_blocks -> %d actions: %s",
                             len(actions),
                             json.dumps([{k: v for k, v in a.items() if k != "content"}
                                         for a in actions]))
            for action in actions:
                self._propose_action(action, source="block")

        if self._pending_tool_cards == 0:
            self.busy = False
        self._set_status()

    def _format_tool_call(self, tool_call: dict, index: int) -> dict:
        self._tool_call_seq += 1
        call_id = f"call_{self._tool_call_seq}"
        tool_call["_id"] = call_id
        args = tool_call.get("arguments", {})
        if self.provider.name == "openai":
            return {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": tool_call.get("name", ""),
                    "arguments": json.dumps(args),
                },
            }
        return {"function": {"name": tool_call.get("name", ""), "arguments": args}}

    def _handle_tool_calls(self, tool_calls: list[dict]) -> None:
        self._tool_results = []
        auto = not self.cfg.get("confirm_actions", True)
        for tool_call in tool_calls:
            action = tool_call_to_action(
                tool_call.get("name", ""), tool_call.get("arguments", {})
            )
            if action is None:
                self._tool_results.append({
                    "id": tool_call.get("_id", ""),
                    "content": f"Error: unknown or invalid tool call: {tool_call.get('name')}",
                })
                continue
            if self.mode == "plan" and action["type"] in (
                "create", "edit", "delete", "move", "mkdir", "shell"
            ):
                self._tool_results.append({
                    "id": tool_call.get("_id", ""),
                    "content": "Rejected: file-modifying actions are disabled in plan mode.",
                })
                continue
            # Read-only actions and auto-confirm mode execute immediately.
            if auto or action["type"] in ("read", "search"):
                target = _action_target(action)
                self._show_spinner(SPINNER_VERBS[action["type"]].format(target))
                self._set_status(STATUS_VERBS[action["type"]])
                result = self._execute_action(action)
                self._hide_spinner()
                self._add_result_line(result)
                self._set_status()
                self._tool_results.append({"id": tool_call.get("_id", ""), "content": result})
            else:
                self.debug_log.debug("[card] mounting ActionCard type=%s path=%s source=tool",
                                 action.get("type"), action.get("path", ""))
                card = ActionCard(action, source="tool")
                card.action["_tool_id"] = tool_call.get("_id", "")
                self._pending_tool_cards += 1
                self.chat.mount(card)
                self.chat.scroll_end(animate=False)

        if self._pending_tool_cards == 0:
            self._continue_after_tools()

    def _continue_after_tools(self) -> None:
        for result in self._tool_results:
            tool_message: dict = {"role": "tool", "content": result["content"]}
            if self.provider.name == "openai" and result.get("id"):
                tool_message["tool_call_id"] = result["id"]
            self.history.append(tool_message)
        self._tool_results = []
        self.run_worker(self._generate(), exclusive=True, group="generate")

    # ------------------------------------------------------------------ #
    # Actions: propose / execute / undo
    # ------------------------------------------------------------------ #

    def _propose_action(self, action: dict, source: str) -> None:
        if not self.cfg.get("confirm_actions", True):
            target = _action_target(action)
            self._show_spinner(
                SPINNER_VERBS.get(action["type"], "Working on {}...").format(target)
            )
            self._set_status(STATUS_VERBS.get(action["type"], "working..."))
            result = self._execute_action(action)
            self._hide_spinner()
            self._add_result_line(result)
            self._set_status()
            return
        self.debug_log.debug("[card] mounting ActionCard type=%s path=%s source=%s",
                         action.get("type"), action.get("path", ""), source)
        card = ActionCard(action, source=source)
        self.chat.mount(card)
        self.chat.scroll_end(animate=False)

    def _capture_undo(self, action: dict) -> dict | None:
        """Build the inverse action BEFORE executing, for the undo stack."""
        kind = action.get("type")
        path = action.get("path", "")
        try:
            if kind == "create":
                target = self.executor._resolve(path)
                if target.is_file():
                    return {"type": "edit", "path": path, "content": self.executor.read(path)}
                return {"type": "delete", "path": path}
            if kind == "edit":
                return {"type": "edit", "path": path, "content": self.executor.read(path)}
            if kind == "delete":
                target = self.executor._resolve(path)
                if target.is_file():
                    return {"type": "create", "path": path, "content": self.executor.read(path)}
                return None  # directory trees are not restorable
            if kind == "move":
                return {"type": "move", "path": action.get("dest", ""), "dest": path}
            if kind == "mkdir":
                target = self.executor._resolve(path)
                if not target.exists():
                    return {"type": "delete", "path": path}
                return None
        except (ActionError, OSError):
            return None
        return None

    def _execute_action(self, action: dict) -> str:
        kind = action.get("type", "?")
        path = action.get("path", "")
        undo = None
        if kind in ("create", "edit", "delete", "move", "mkdir"):
            undo = self._capture_undo(action)
        try:
            result = self.executor.apply(action)
        except ActionError as exc:
            self.pmem.log_action(f"{kind}:failed", path, str(exc))
            return f"Error: {exc}"
        if undo is not None:
            self.pmem.push_undo(undo)
        self.pmem.log_action(kind, path, result[:500])
        if kind in ("create", "edit"):
            self.pmem.index_file(path)
        elif kind == "delete":
            self.pmem.remove_file(path)
        elif kind == "move":
            self.pmem.remove_file(path)
            self.pmem.index_file(action.get("dest", ""))
        return result

    @on(Button.Pressed)
    def _on_card_button(self, event: Button.Pressed) -> None:
        node = event.button
        while node is not None and not isinstance(node, ActionCard):
            node = node.parent
        if node is None or node.resolved:
            return
        card: ActionCard = node

        if event.button.has_class("btn-edit"):
            card.toggle_edit()
            return

        if event.button.has_class("btn-apply"):
            action = card.final_action()
            result = self._execute_action(action)
            card.mark_resolved("applied" if not result.startswith("Error:") else "failed")
            self.add_system(result if len(result) < 1500 else result[:1500] + "\n... (truncated)")
            verdict_content = result
        elif event.button.has_class("btn-reject"):
            card.mark_resolved("rejected")
            verdict_content = "User rejected this action."
        else:
            return

        if card.source == "tool":
            self._tool_results.append({
                "id": card.action.get("_tool_id", ""),
                "content": verdict_content,
            })
            self._pending_tool_cards = max(0, self._pending_tool_cards - 1)
            if self._pending_tool_cards == 0:
                self._continue_after_tools()
        self.chat.scroll_end(animate=False)

    # ------------------------------------------------------------------ #
    # Slash commands
    # ------------------------------------------------------------------ #

    def handle_command(self, text: str) -> None:
        parts = text.split(maxsplit=1)
        command = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if command == "/help":
            self.add_system(HELP_TEXT)
        elif command == "/tree":
            self.action_show_tree()
        elif command == "/read":
            if not arg:
                self.add_system("Usage: /read <path>")
                return
            try:
                content = self.executor.read(arg)
                self.add_system(f"── {arg} ──\n{content}")
            except ActionError as exc:
                self.add_system(f"Error: {exc}")
        elif command == "/search":
            if not arg:
                self.add_system("Usage: /search <text>")
                return
            try:
                self.add_system(self.executor.search(arg))
            except ActionError as exc:
                self.add_system(f"Error: {exc}")
        elif command == "/run":
            if not arg:
                self.add_system("Usage: /run <command>")
                return
            try:
                output = self.executor.shell(arg)
                self.pmem.log_action("shell", "", arg)
                self.add_system(f"$ {arg}\n{output}")
            except ActionError as exc:
                self.add_system(f"Error: {exc}")
        elif command == "/clear":
            self.action_clear_chat()
        elif command == "/memory":
            self._show_memory()
        elif command == "/plan":
            self._set_mode("plan")
        elif command == "/build":
            self._set_mode("build")
        elif command == "/models":
            self.run_worker(self._list_models_command(), exclusive=False)
        elif command == "/model":
            if not arg:
                self.add_system("Usage: /model <name>  (or press Ctrl+S)")
                return
            self._switch_model(arg)
        elif command == "/skills":
            self._skills_list(arg)
        elif command == "/skill":
            self._skill_command(arg)
        elif command == "/config":
            self._config_command(arg)
        elif command == "/undo":
            self._undo_last()
        elif command == "/prefs":
            prefs = self.gmem.read_md()
            if prefs.strip():
                self.add_system(f"── {self.gmem.md_path} ──\n{prefs}")
            else:
                self.add_system(
                    f"No global preferences yet. Create {self.gmem.md_path} "
                    "with notes Echo should always know about you."
                )
        else:
            self.add_system(f"Unknown command: {command}  (/help for the list)")

    # ------------------------------------------------------------------ #
    # Config
    # ------------------------------------------------------------------ #

    def _config_command(self, arg: str) -> None:
        tokens = arg.split(maxsplit=1)
        settings = config_mod.USER_SETTINGS

        if not tokens:
            lines = ["Settings (~/.echo/config.json):", ""]
            for key in settings:
                lines.append(f"  {key} = {json.dumps(self.cfg.get(key))}")
            lines += ["", "Change with: /config <key> <value>"]
            self.add_system("\n".join(lines))
            return

        key = tokens[0].lower()
        if key not in settings:
            self.add_system(
                f"Unknown setting: {key}. Valid keys: {', '.join(settings)}"
            )
            return

        if len(tokens) == 1:
            self.add_system(f"{key} = {json.dumps(self.cfg.get(key))}")
            return

        raw = tokens[1].strip()
        spec = settings[key]
        value: object
        if spec is bool:
            if raw.lower() in ("true", "on", "yes", "1"):
                value = True
            elif raw.lower() in ("false", "off", "no", "0"):
                value = False
            else:
                self.add_system(f"{key} expects true or false.")
                return
        elif spec is int:
            try:
                value = int(raw)
            except ValueError:
                self.add_system(f"{key} expects a number.")
                return
            if value < 0:
                self.add_system(f"{key} must be >= 0.")
                return
        else:  # tuple of allowed strings
            value = raw.lower()
            if value not in spec:
                self.add_system(f"{key} must be one of: {', '.join(spec)}")
                return

        self.cfg[key] = value
        config_mod.save(self.cfg)
        self._apply_setting(key, value)
        self.add_system(f"✓ {key} → {json.dumps(value)} (saved)")

    def _apply_setting(self, key: str, value: object) -> None:
        """Real-time effects; most settings are read fresh where they're used."""
        if key == "mode" and value != self.mode:
            self._set_mode(str(value))
        elif key == "confirm_actions":
            self._refresh_topbar()

    def action_toggle_confirm(self) -> None:
        self.cfg["confirm_actions"] = not self.cfg.get("confirm_actions", True)
        config_mod.save(self.cfg)
        self._refresh_topbar()
        if self.cfg["confirm_actions"]:
            self.add_system("confirm_actions ON - actions show Apply/Reject cards.")
        else:
            self.add_system("confirm_actions OFF [auto] - actions apply immediately.")

    def _show_memory(self) -> None:
        facts = self.pmem.get_facts()
        actions = self.pmem.get_recent_actions(limit=10)
        lines = [f"Project memory ({self.pmem.db_path})", ""]
        lines.append(f"Conversation rows: {len(self.pmem.get_history(limit=1000))}")
        if facts:
            lines += ["", "Facts:"] + [f"  {k}: {v}" for k, v in facts.items()]
        if actions:
            lines += ["", "Recent actions:"] + [
                f"  {a['action_type']} {a['path']}".rstrip() for a in actions
            ]
        if not facts and not actions:
            lines.append("No facts or actions recorded yet.")
        self.add_system("\n".join(lines))

    # ------------------------------------------------------------------ #
    # Skills
    # ------------------------------------------------------------------ #

    def _skills_list(self, arg: str) -> None:
        if arg.strip().lower() == "active":
            if not self.active_skills:
                self.add_system("No skills active. Activate one with /skill <name>.")
                return
            self.add_system("Active skills:\n" + "\n".join(
                f"  ✦ {name}" for name in sorted(self.active_skills)))
            return
        skills = self.pmem.list_skills()
        if not skills:
            self.add_system(
                "No skills found.\n"
                f"  Global:  {GLOBAL_SKILLS_DIR}\n"
                f"  Project: {self.pmem.project_skills_dir}\n"
                "Each skill is a folder with a SKILL.md inside "
                "(github.com/anthropics/skills format)."
            )
            return
        lines = ["Available skills:  (✦ = active)"]
        for skill in skills:
            active = "✦ " if skill["name"] in self.active_skills else "  "
            description = f" - {skill['description']}" if skill["description"] else ""
            lines.append(f"  {active}{skill['name']} [{skill['source']}]{description}")
        lines.append("")
        lines.append("/skill <name> to activate · /skill off to deactivate all")
        self.add_system("\n".join(lines))

    def _skill_command(self, arg: str) -> None:
        tokens = arg.split()
        if not tokens:
            self.add_system(
                "Usage: /skill <name> | /skill off [name] | "
                "/skill save [--global] <name> | /skill install <url> [--project] | "
                "/skill uninstall <name> | /skill update"
            )
            return

        if tokens[0].lower() == "off":
            if len(tokens) == 1:
                if not self.active_skills:
                    self.add_system("No skills were active.")
                else:
                    self.active_skills.clear()
                    self.add_system("All skills deactivated.")
            else:
                name = tokens[1]
                if name in self.active_skills:
                    self.active_skills.discard(name)
                    self.add_system(f"Skill '{name}' deactivated.")
                else:
                    self.add_system(f"Skill '{name}' is not active.")
            self._refresh_topbar()
            return

        if tokens[0].lower() == "install":
            rest = tokens[1:]
            project = "--project" in rest
            urls = [t for t in rest if not t.startswith("--")]
            if not urls:
                self.add_system("Usage: /skill install <github-url> [--project]")
                return
            dest = self.pmem.project_skills_dir if project else GLOBAL_SKILLS_DIR
            self.run_worker(self._install_skills_worker(urls[0], dest),
                            exclusive=False)
            return

        if tokens[0].lower() == "uninstall":
            if len(tokens) < 2:
                self.add_system("Usage: /skill uninstall <name>")
                return
            self._uninstall_skill(tokens[1])
            return

        if tokens[0].lower() == "update":
            pairs = collect_sources([GLOBAL_SKILLS_DIR, self.pmem.project_skills_dir])
            if not pairs:
                self.add_system(
                    "No installed skills with source metadata (echo-meta.json) found."
                )
                return
            self.run_worker(self._update_skills_worker(pairs), exclusive=False)
            return

        if tokens[0].lower() == "save":
            rest = [t for t in tokens[1:] if t != "--global"]
            global_ = "--global" in tokens[1:]
            if not rest:
                self.add_system("Usage: /skill save [--global] <name>")
                return
            name = rest[0].lower().replace(" ", "-")
            if self.busy:
                self.add_system("Echo is still responding - try again in a moment.")
                return
            if not self.history:
                self.add_system("Nothing to analyze yet - have a conversation first.")
                return
            if not self.model:
                self.add_system("No model selected.")
                return
            self.run_worker(self._save_skill_worker(name, global_), exclusive=True,
                            group="generate")
            return

        # Activate
        name = tokens[0]
        available = {s["name"]: s for s in self.pmem.list_skills()}
        if name not in available:
            options = ", ".join(sorted(available)) or "(none found)"
            self.add_system(f"Unknown skill: '{name}'. Available: {options}")
            return
        self.active_skills.add(name)
        self._refresh_topbar()
        source = available[name]["source"]
        self.add_system(
            f"✦ Skill '{name}' activated ({source}). "
            f"{len(self.active_skills)} active - it now shapes every response."
        )

    async def _install_skills_worker(self, url: str, dest: Path) -> None:
        self._set_status("installing skills...")
        self._show_spinner(f"Installing skills from {url}...")
        widget = self.add_system("")
        lines: list[str] = []

        def progress(message: str) -> None:
            lines.append(message)
            widget.set_text("\n".join(lines))
            self.chat.scroll_end(animate=False)

        try:
            await install_skills_from_github(url, dest, progress)
        except InstallError as exc:
            progress(f"✗ {exc}")
        finally:
            self._hide_spinner()
            self._set_status()
        self.debug_log.debug("[skill] install from %s -> %s", url, dest)

    def _uninstall_skill(self, name: str) -> None:
        skill = next((s for s in self.pmem.list_skills() if s["name"] == name), None)
        if skill is None:
            self.add_system(f"Skill not found: {name}")
            return
        folder = Path(skill["path"]).parent

        def on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                self.add_system("Uninstall cancelled.")
                return
            try:
                shutil.rmtree(folder)
            except OSError as exc:
                self.add_system(f"Could not remove {folder}: {exc}")
                return
            self.active_skills.discard(name)
            self._refresh_topbar()
            self.add_system(f"✓ Skill '{name}' uninstalled ({folder})")

        self.push_screen(
            ConfirmScreen(f"Uninstall skill '{name}'?\n\nThis deletes:\n{folder}"),
            on_confirm,
        )

    async def _update_skills_worker(self, pairs: list[tuple[str, Path]]) -> None:
        self._set_status("updating skills...")
        self._show_spinner("Updating installed skills...")
        widget = self.add_system("")
        lines: list[str] = []

        def progress(message: str) -> None:
            lines.append(message)
            widget.set_text("\n".join(lines))
            self.chat.scroll_end(animate=False)

        try:
            for source, base in pairs:
                try:
                    await install_skills_from_github(source, base, progress)
                except InstallError as exc:
                    progress(f"✗ {source} ({exc})")
        finally:
            self._hide_spinner()
            self._set_status()

    async def _save_skill_worker(self, name: str, global_: bool) -> None:
        self.busy = True
        self.add_system(f"Analyzing conversation to create skill '{name}'...")
        prompt = (
            "Analyze this conversation and create a SKILL.md file that captures "
            "the key patterns, decisions, conventions and guidelines discussed. "
            "Format it with YAML frontmatter (name, description) followed by "
            "clear markdown instructions. Be concise and actionable."
        )
        # Deliberately NOT _build_messages(): the build-mode prompt tells the
        # model to emit action blocks, which would pollute the skill body.
        messages = (
            [{
                "role": "system",
                "content": (
                    "You write SKILL.md files. Respond ONLY with the SKILL.md "
                    f"content: YAML frontmatter (name: {name}, description) "
                    "followed by markdown instructions. No tool calls, no "
                    "action blocks, no commentary."
                ),
            }]
            + [m for m in self.history if m.get("role") in ("user", "assistant")]
            + [{"role": "user", "content": prompt}]
        )
        text = ""
        try:
            async for chunk in self.provider.stream(messages, self.model, None):
                if isinstance(chunk, str):
                    text += chunk
        except ProviderError as exc:
            self.add_system(f"⚠ Skill generation failed: {exc}")
            self.busy = False
            return
        finally:
            self.busy = False

        content = _extract_skill_md(text, name)
        path = self.pmem.save_skill(name, content, global_=global_)
        self.active_skills.add(name)
        self._refresh_topbar()
        scope = "global" if global_ else "project"
        self.debug_log.debug("[skill] saved %s skill '%s' to %s", scope, name, path)
        self.add_system(f"✦ Skill '{name}' saved ({scope}: {path}) and activated.")

    async def _list_models_command(self) -> None:
        try:
            models = await self.provider.list_models()
            self.connected = True
        except ProviderError as exc:
            self.connected = False
            self.add_system(f"⚠ {exc}")
            self._refresh_topbar()
            return
        self._refresh_topbar()
        if not models:
            self.add_system("No models available.")
            return
        lines = ["Available models:"]
        for name in models:
            bolt = "⚡ " if model_supports_tools(name) else "   "
            current = "  ← current" if name == self.model else ""
            lines.append(f"  {bolt}{name}{current}")
        self.add_system("\n".join(lines))

    def _switch_model(self, name: str) -> None:
        self.model = name
        self.cfg["model"] = name
        config_mod.save(self.cfg)
        self._refresh_topbar()
        bolt = "⚡ tool calling" if model_supports_tools(name) \
            else "action-block fallback"
        self.add_system(f"Model switched to {name} ({bolt}). Conversation preserved.")

    def _set_mode(self, mode: str) -> None:
        self.mode = mode
        self._refresh_topbar()
        if mode == "plan":
            self.add_system("◎ PLAN mode - Echo will discuss and design, not modify files.")
        else:
            self.add_system("▶ BUILD mode - Echo can create and edit files.")

    def _undo_last(self) -> None:
        undo = self.pmem.pop_undo()
        if undo is None:
            self.add_system("Nothing to undo.")
            return
        try:
            result = self.executor.apply(undo)
            self.pmem.log_action(f"undo:{undo.get('type')}", undo.get("path", ""), result[:500])
            self.add_system(f"Undo: {result}")
        except ActionError as exc:
            self.add_system(f"Undo failed: {exc}")

    # ------------------------------------------------------------------ #
    # Key bindings
    # ------------------------------------------------------------------ #

    def action_toggle_mode(self) -> None:
        self._set_mode("plan" if self.mode == "build" else "build")

    def action_pick_model(self) -> None:
        self.run_worker(self._open_model_picker(), exclusive=False)

    async def _open_model_picker(self) -> None:
        try:
            models = await self.provider.list_models()
            self.connected = True
        except ProviderError:
            self.connected = False
            models = []
        self._refresh_topbar()

        def on_picked(name: str | None) -> None:
            if name:
                self._switch_model(name)

        await self.push_screen(ModelPickerScreen(models, self.model), on_picked)

    def action_clear_chat(self) -> None:
        self.chat.remove_children()
        self.history.clear()
        self.pmem.clear_history()
        self._pending_tool_cards = 0
        self._tool_results = []
        self.busy = False
        self.add_system("Conversation cleared.")

    def action_show_tree(self) -> None:
        tree = self.pmem.build_tree(max_depth=3)
        files = self.pmem.count_files()
        self.add_system(f"{tree}\n\n{files} files")
