"""
Project Echo — Terminal UI
Main application entry point.
"""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
from typing import Optional

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import (
    Button, Footer, Header, Input, Label, Markdown,
    OptionList, Static, TextArea,
)
from textual.widgets.option_list import Option
from rich.text import Text

from echo.core.config import load as load_config, save as save_config, get_provider
from echo.core.executor import Executor, ActionError
from echo.memory.manager import ProjectMemory, GlobalMemory
from echo.tools.definitions import (
    TOOLS, model_supports_tools, parse_action_blocks, tool_call_to_action,
)


# ── CSS ───────────────────────────────────────────────────────────────────────

CSS = """
Screen {
    background: #090b10;
}

/* Header bar */
#header-bar {
    height: 3;
    background: #0f1118;
    border-bottom: solid #1f2535;
    layout: horizontal;
    align: left middle;
    padding: 0 2;
}
#logo {
    color: #00e5ff;
    text-style: bold;
    width: auto;
    margin-right: 2;
}
#mode-btn {
    background: #0f2a1e;
    border: solid #00e5aa;
    color: #00e5aa;
    width: auto;
    min-width: 12;
    height: 1;
    margin-right: 2;
}
#mode-btn.plan {
    background: #1e1030;
    border: solid #b06fff;
    color: #b06fff;
}
#model-label {
    color: #4a5568;
    width: auto;
    margin-right: 1;
}
#model-name {
    color: #7a8899;
    width: auto;
}
#status-dot {
    color: #4a5568;
    width: 3;
}
#status-dot.connected {
    color: #00e5ff;
}
#project-path {
    color: #2a3248;
    width: 1fr;
    text-align: right;
}

/* Context bar */
#ctx-bar {
    height: 1;
    background: #0f1118;
    border-bottom: solid #1f2535;
    layout: horizontal;
    align: left middle;
    padding: 0 2;
}
#ctx-label {
    color: #2a3248;
    width: auto;
    margin-right: 1;
}
#ctx-info {
    color: #4a5568;
    width: 1fr;
}
#ctx-mode-label {
    color: #4a5568;
    width: auto;
}

/* Chat area */
#chat-scroll {
    height: 1fr;
    border: none;
    background: #090b10;
    padding: 0 1;
}
#messages {
    padding: 1 0;
}

/* Message bubbles */
.msg-wrap {
    margin: 0 0 1 0;
}
.msg-label {
    color: #2a3248;
    text-style: bold;
    height: 1;
}
.msg-label.you {
    color: #b06fff;
    text-align: right;
}
.msg-label.echo {
    color: #00e5ff;
}
.msg-bubble {
    background: #0c0f18;
    border-left: solid #1f2535;
    padding: 0 1;
    color: #dce6f0;
    margin-bottom: 0;
}
.msg-bubble.you {
    background: #131826;
    border-left: solid #2a3248;
}
.system-msg {
    color: #2a3248;
    text-align: center;
    margin: 0 0 1 0;
}

/* Action card */
.action-card {
    border: solid #b06fff;
    background: #0a0d15;
    margin: 0 0 1 0;
    padding: 0 1 1 1;
}
.action-card-head {
    height: 1;
    layout: horizontal;
    margin-bottom: 1;
    background: #130a20;
    padding: 0 1;
}
.action-badge {
    width: auto;
    margin-right: 1;
    text-style: bold;
}
.badge-create  { color: #00e5aa; }
.badge-edit    { color: #ffb347; }
.badge-delete  { color: #ff4d6d; }
.badge-shell   { color: #00e5ff; }
.badge-move    { color: #b06fff; }
.badge-mkdir   { color: #00e5aa; }
.badge-read    { color: #7a8899; }
.badge-search  { color: #7a8899; }
.action-path {
    color: #7a8899;
    width: 1fr;
}
.action-desc {
    color: #4a5568;
    margin-bottom: 1;
}
.diff-stats {
    color: #4a5568;
    height: 1;
    margin-bottom: 1;
}
.diff-add { color: #4ade80; }
.diff-rem { color: #f87171; }
.action-preview {
    background: #06080e;
    border: solid #1f2535;
    color: #4a5568;
    height: auto;
    max-height: 8;
    padding: 0 1;
    margin-bottom: 1;
    overflow-y: auto;
}
.action-btns {
    layout: horizontal;
    height: 3;
    margin-top: 1;
}
.btn-apply {
    background: #0f2a1e;
    border: solid #00e5aa;
    color: #00e5aa;
    margin-right: 1;
    width: 14;
}
.btn-reject {
    background: #200810;
    border: solid #ff4d6d;
    color: #ff4d6d;
    margin-right: 1;
    width: 14;
}
.btn-edit-inline {
    background: #1e1030;
    border: solid #b06fff;
    color: #b06fff;
    width: 10;
}
.action-done {
    height: 1;
    color: #00e5aa;
    margin-top: 1;
}
.action-done.fail {
    color: #ff4d6d;
}

/* Inline editor */
.inline-editor {
    height: 12;
    border: solid #b06fff;
    margin-bottom: 1;
    display: none;
}
.inline-editor.visible {
    display: block;
}

/* Input area */
#input-area {
    height: 5;
    background: #0f1118;
    border-top: solid #1f2535;
    padding: 1 2;
    layout: horizontal;
    align: left middle;
}
#msg-input {
    width: 1fr;
    background: #161922;
    border: solid #1f2535;
    color: #dce6f0;
    height: 3;
    margin-right: 1;
}
#msg-input:focus {
    border: solid #00e5ff;
}
#send-btn {
    background: #0a2030;
    border: solid #00e5ff;
    color: #00e5ff;
    width: 10;
    height: 3;
}

/* Model selector overlay */
#model-overlay {
    layer: overlay;
    background: #0f1118;
    border: solid #2a3248;
    width: 50;
    height: 20;
    offset: 20 3;
    display: none;
}
#model-overlay.visible {
    display: block;
}
#model-list {
    height: 1fr;
    background: #0f1118;
}

/* Footer */
Footer {
    background: #0f1118;
    color: #2a3248;
}
"""


# ── Widgets ───────────────────────────────────────────────────────────────────

class MessageBubble(Widget):
    def __init__(self, role: str, content: str, **kwargs):
        super().__init__(**kwargs)
        self.role    = role
        self.content = content

    def compose(self) -> ComposeResult:
        lbl = Label(("You" if self.role == "user" else "Echo"),
                    classes=f"msg-label {'you' if self.role == 'user' else 'echo'}")
        yield lbl
        yield Markdown(self.content, classes=f"msg-bubble {'you' if self.role == 'user' else ''}")

    def append_text(self, text: str) -> None:
        self.content += text
        try:
            md = self.query_one(Markdown)
            md.update(self.content)
        except NoMatches:
            pass


class ActionCard(Widget):
    """Interactive action card with Apply/Reject/Edit buttons."""

    COMPONENT_CLASSES = {"action-card"}

    def __init__(self, action: dict, action_id: int, **kwargs):
        super().__init__(**kwargs, classes="action-card")
        self.action    = action
        self.action_id = action_id
        self.resolved  = False
        self._editing  = False

    def compose(self) -> ComposeResult:
        act     = self.action.get("action", "create")
        path    = self.action.get("path") or self.action.get("command") or ""
        desc    = self.action.get("description", "")
        content = self.action.get("content") or ""

        badge_class = f"badge-{act}"
        icons = {"create":"✚","edit":"✎","delete":"✕","move":"→",
                 "mkdir":"▶","shell":"$","read":"👁","search":"🔍"}
        icon = icons.get(act, "•")

        with Horizontal(classes="action-card-head"):
            yield Label(f"{icon} {act.upper()}", classes=f"action-badge {badge_class}")
            yield Label(path[:60], classes="action-path")

        yield Label(desc, classes="action-desc")

        # Preview
        if act == "shell":
            yield Static(f"$ {path}", classes="action-preview")
        elif content:
            lines   = content.split("\n")
            preview = "\n".join(lines[:10]) + ("\n..." if len(lines) > 10 else "")
            yield Static(preview, classes="action-preview", id=f"preview-{self.action_id}")
        elif self.action.get("destination"):
            yield Static(f"→ {self.action['destination']}", classes="action-preview")

        # Inline editor (hidden by default)
        yield TextArea(content, classes="inline-editor", id=f"editor-{self.action_id}")

        with Horizontal(classes="action-btns", id=f"btns-{self.action_id}"):
            yield Button("✓ Apply",  classes="btn-apply",       id=f"apply-{self.action_id}")
            yield Button("✕ Reject", classes="btn-reject",      id=f"reject-{self.action_id}")
            if act in ("create", "edit") and content:
                yield Button("✎ Edit", classes="btn-edit-inline", id=f"edit-{self.action_id}")

    def mark_done(self, ok: bool, message: str = "") -> None:
        self.resolved = True
        try:
            btns = self.query_one(f"#btns-{self.action_id}")
            btns.remove()
        except NoMatches:
            pass
        msg = message or ("✓ Applied" if ok else "✕ Failed")
        self.mount(Label(msg, classes=f"action-done {'fail' if not ok else ''}"))

    def toggle_edit(self) -> None:
        self._editing = not self._editing
        try:
            editor  = self.query_one(f"#editor-{self.action_id}", TextArea)
            preview = self.query_one(f"#preview-{self.action_id}", Static)
            if self._editing:
                editor.add_class("visible")
                preview.display = False
            else:
                editor.remove_class("visible")
                preview.display = True
        except NoMatches:
            pass

    def get_content(self) -> str:
        """Get content — edited version if in edit mode, original otherwise."""
        if self._editing:
            try:
                return self.query_one(f"#editor-{self.action_id}", TextArea).text
            except NoMatches:
                pass
        return self.action.get("content") or ""


# ── Main App ──────────────────────────────────────────────────────────────────

class EchoApp(App):
    """Project Echo — Terminal AI Coding Assistant."""

    CSS = CSS
    TITLE = "Project Echo"

    BINDINGS = [
        Binding("ctrl+c",     "quit",          "Quit",          show=True),
        Binding("ctrl+m",     "toggle_mode",   "Plan/Build",    show=True),
        Binding("ctrl+l",     "clear_chat",    "Clear",         show=True),
        Binding("ctrl+t",     "show_tree",     "Tree",          show=True),
        Binding("ctrl+p",     "open_prefs",    "Preferences",   show=True),
        Binding("ctrl+s",     "pick_model",    "Model",         show=True),
        Binding("escape",     "close_overlay", "Close",         show=False),
    ]

    mode:          reactive[str]  = reactive("build")
    current_model: reactive[str]  = reactive("")
    connected:     reactive[bool] = reactive(False)

    def __init__(self, project_root: str):
        super().__init__()
        self.project_root = project_root
        self.cfg          = load_config()
        self.memory       = ProjectMemory(project_root)
        self.glob_mem     = GlobalMemory()
        self.executor     = Executor(project_root)
        self.provider     = get_provider(self.cfg)
        self.history:     list[dict] = []
        self.pending:     dict[int, ActionCard] = {}
        self._action_counter = 0
        self._streaming      = False
        self._stream_bubble: Optional[MessageBubble] = None
        self.mode          = self.cfg.get("mode", "build")
        self.current_model = self.cfg.get("model", "")

    def compose(self) -> ComposeResult:
        # Header
        with Horizontal(id="header-bar"):
            yield Label("◈ PROJECT ECHO", id="logo")
            yield Button(
                "▶ BUILD" if self.mode == "build" else "◎ PLAN",
                id="mode-btn",
                classes="" if self.mode == "build" else "plan",
            )
            yield Label("Model:", id="model-label")
            yield Label(self.current_model or "— none —", id="model-name")
            yield Label("●", id="status-dot")
            yield Label(str(Path(self.project_root).name), id="project-path")

        # Context bar
        with Horizontal(id="ctx-bar"):
            yield Label("CTX", id="ctx-label")
            yield Label("No file context — use /tree or /read <path>", id="ctx-info")
            yield Label("Ctrl+S: model  Ctrl+M: mode", id="ctx-mode-label")

        # Chat scroll area
        with ScrollableContainer(id="chat-scroll"):
            yield Vertical(id="messages")

        # Input area
        with Horizontal(id="input-area"):
            yield Input(
                placeholder="Message Echo... (/ for commands)",
                id="msg-input",
            )
            yield Button("Send ↑", id="send-btn")

        # Model selector overlay (hidden by default)
        with Vertical(id="model-overlay"):
            yield Label("  Select model  ", classes="system-msg")
            yield OptionList(id="model-list")

        yield Footer()

    def on_mount(self) -> None:
        self._check_connection()
        self._auto_init()
        self.query_one("#msg-input", Input).focus()

    # ── Connection & init ─────────────────────────────────────────────────────

    @work(exclusive=True)
    async def _check_connection(self) -> None:
        ok = await self.provider.health()
        self.connected = ok
        dot = self.query_one("#status-dot", Label)
        dot.update("●" if ok else "○")
        if ok:
            dot.add_class("connected")
        else:
            self._add_system("⚠ Cannot reach model server. Check Settings → projectEcho config.")

        if ok and not self.current_model:
            models = await self.provider.list_models()
            if models:
                self.current_model = models[0]
                self._update_model_label()

    @work(exclusive=False)
    async def _auto_init(self) -> None:
        """Show project summary on first launch."""
        tree = self.memory.build_tree(max_depth=2)
        files = self.memory.get_file_index()
        readme = ""
        for name in ("README.md", "readme.md"):
            p = Path(self.project_root) / name
            if p.exists():
                readme = p.read_text(encoding="utf-8")[:300]
                break
        msg = f"◈ **Project Echo** — {Path(self.project_root).name}\n\n"
        msg += f"```\n{tree}\n```\n"
        if readme:
            msg += f"\n**README:** {readme[:200]}..."
        if files:
            msg += f"\n\n**Tracked files:** {len(files)}"
        msg += "\n\nType your message or `/help` for commands."
        self._add_system(msg)

    # ── UI helpers ────────────────────────────────────────────────────────────

    def _add_system(self, text: str) -> None:
        messages = self.query_one("#messages", Vertical)
        messages.mount(Static(text, classes="system-msg"))
        self._scroll_bottom()

    def _add_bubble(self, role: str, content: str = "") -> MessageBubble:
        bubble = MessageBubble(role, content)
        messages = self.query_one("#messages", Vertical)
        messages.mount(bubble)
        self._scroll_bottom()
        return bubble

    def _add_action_card(self, action: dict) -> ActionCard:
        self._action_counter += 1
        card = ActionCard(action, self._action_counter)
        self.pending[self._action_counter] = card
        messages = self.query_one("#messages", Vertical)
        messages.mount(card)
        self._scroll_bottom()
        return card

    def _scroll_bottom(self) -> None:
        try:
            scroll = self.query_one("#chat-scroll", ScrollableContainer)
            scroll.scroll_end(animate=False)
        except NoMatches:
            pass

    def _update_model_label(self) -> None:
        try:
            lbl = self.query_one("#model-name", Label)
            prefix = "⚡ " if model_supports_tools(self.current_model) else ""
            lbl.update(prefix + self.current_model)
        except NoMatches:
            pass

    def _update_ctx_bar(self, text: str) -> None:
        try:
            self.query_one("#ctx-info", Label).update(text)
        except NoMatches:
            pass

    # ── Input handling ────────────────────────────────────────────────────────

    @on(Input.Submitted, "#msg-input")
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        self.query_one("#msg-input", Input).value = ""
        if text.startswith("/"):
            await self._handle_slash(text)
        else:
            await self._send_message(text)

    @on(Button.Pressed, "#send-btn")
    async def on_send_pressed(self) -> None:
        inp  = self.query_one("#msg-input", Input)
        text = inp.value.strip()
        if not text:
            return
        inp.value = ""
        if text.startswith("/"):
            await self._handle_slash(text)
        else:
            await self._send_message(text)

    @on(Button.Pressed, "#mode-btn")
    def on_mode_pressed(self) -> None:
        self.action_toggle_mode()

    # ── Action card buttons ───────────────────────────────────────────────────

    @on(Button.Pressed)
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""

        if btn_id.startswith("apply-"):
            action_id = int(btn_id.split("-", 1)[1])
            await self._execute_action(action_id)

        elif btn_id.startswith("reject-"):
            action_id = int(btn_id.split("-", 1)[1])
            card = self.pending.get(action_id)
            if card:
                card.mark_done(False, "✕ Rejected")
                del self.pending[action_id]

        elif btn_id.startswith("edit-"):
            action_id = int(btn_id.split("-", 1)[1])
            card = self.pending.get(action_id)
            if card:
                card.toggle_edit()

    # ── Slash commands ────────────────────────────────────────────────────────

    async def _handle_slash(self, raw: str) -> None:
        parts = raw.strip().split(None, 1)
        cmd   = parts[0].lower()
        arg   = parts[1] if len(parts) > 1 else ""

        self._add_bubble("user", raw)

        match cmd:
            case "/help":
                self._add_system(
                    "**Commands:**\n\n"
                    "- `/help` — this list\n"
                    "- `/tree` — show project tree\n"
                    "- `/read <path>` — read a file\n"
                    "- `/search <text>` — search in files\n"
                    "- `/run <command>` — run a shell command\n"
                    "- `/clear` — clear chat history\n"
                    "- `/memory` — show project memory status\n"
                    "- `/plan` — switch to Plan mode\n"
                    "- `/build` — switch to Build mode\n"
                    "- `/models` — list available models\n"
                    "- `/model <name>` — switch model\n"
                    "- `/prefs` — open preferences.md\n"
                    "- `/undo` — undo last file action\n"
                )

            case "/tree":
                tree = self.memory.build_tree(max_depth=4)
                self._add_system(f"```\n{tree}\n```")

            case "/read":
                if not arg:
                    self._add_system("⚠ Usage: `/read <path>`")
                    return
                try:
                    r = self.executor.read(arg)
                    ext   = Path(arg).suffix.lstrip(".")
                    self._add_system(f"**{arg}**\n\n```{ext}\n{r['content'][:3000]}\n```")
                    self._update_ctx_bar(f"Reading: {arg}")
                except ActionError as e:
                    self._add_system(f"⚠ {e}")

            case "/search":
                if not arg:
                    self._add_system("⚠ Usage: `/search <text>`")
                    return
                results = self.executor.search(arg)
                if not results:
                    self._add_system(f"No matches for `{arg}`")
                    return
                lines = [f"**{len(results)} match(es) for `{arg}`:**\n"]
                for r in results[:20]:
                    lines.append(f"`{r['file']}:{r['line']}` — {r['content'].strip()}")
                self._add_system("\n".join(lines))

            case "/run":
                if not arg:
                    self._add_system("⚠ Usage: `/run <command>`")
                    return
                self._add_system(f"Running `{arg}`...")
                r = self.executor.shell(arg)
                out = ""
                if r["stdout"]:
                    out += f"```\n{r['stdout'].strip()}\n```"
                if r["stderr"]:
                    out += f"\n**stderr:**\n```\n{r['stderr'].strip()}\n```"
                if not out:
                    out = f"Exit code: {r['exit_code']}"
                self._add_system(out)
                self.memory.log_action("shell", arg, "success" if r["ok"] else "error")

            case "/clear":
                self.memory.clear_history()
                self.history.clear()
                messages = self.query_one("#messages", Vertical)
                await messages.remove_children()
                self.pending.clear()
                self._add_system("◈ History cleared.")

            case "/memory":
                files   = self.memory.get_file_index()
                facts   = self.memory.get_facts()
                actions = self.memory.get_recent_actions(5)
                lines = [
                    f"**Project:** `{self.project_root}`",
                    f"**Tracked files:** {len(files)}",
                ]
                if facts:
                    lines.append("\n**Facts:**")
                    for k, v in facts.items():
                        lines.append(f"  - {k}: {v}")
                if actions:
                    lines.append("\n**Recent actions:**")
                    for a in actions:
                        lines.append(f"  - {a['action']} `{a['path']}` → {a['status']} ({a['ts'][:16]})")
                self._add_system("\n".join(lines))

            case "/plan":
                self.mode = "plan"
                self._update_mode_ui()
                self._add_system("◎ **Plan mode** — Echo will analyze only, no file changes.")

            case "/build":
                self.mode = "build"
                self._update_mode_ui()
                self._add_system("▶ **Build mode** — Full file access enabled.")

            case "/models":
                models = await self.provider.list_models()
                if not models:
                    self._add_system("⚠ No models found. Is the model server running?")
                    return
                lines = ["**Available models:**\n"]
                for m in models:
                    prefix = "⚡ " if model_supports_tools(m) else "  "
                    lines.append(f"{prefix}`{m}`")
                lines.append("\n⚡ = supports native tool calling")
                self._add_system("\n".join(lines))

            case "/model":
                if not arg:
                    self._add_system(f"Current model: `{self.current_model}`")
                    return
                self.current_model = arg
                self.cfg["model"]  = arg
                save_config(self.cfg)
                self._update_model_label()
                self._add_system(f"✓ Model set to `{arg}`")

            case "/prefs":
                prefs_path = Path.home() / ".echo" / "preferences.md"
                self._add_system(f"Preferences file: `{prefs_path}`\nEdit it with your text editor and restart Echo.")

            case "/undo":
                entry = self.memory.pop_undo()
                if not entry:
                    self._add_system("Nothing to undo.")
                    return
                target = Path(self.project_root) / entry["path"]
                target.write_text(entry["content"], encoding="utf-8")
                self.memory.log_action("undo", entry["path"], "success")
                self._add_system(f"↩ Reverted `{entry['path']}`")

            case _:
                self._add_system(f"Unknown command `{cmd}`. Type `/help`.")

    # ── Chat ──────────────────────────────────────────────────────────────────

    async def _send_message(self, text: str) -> None:
        if self._streaming:
            return
        self._add_bubble("user", text)
        self.history.append({"role": "user", "content": text})
        self._stream_bubble = self._add_bubble("echo", "")
        self._streaming      = True
        self._stream_text    = ""
        self._stream_actions: list[dict] = []
        self._stream_worker()

    @work(thread=False)
    async def _stream_worker(self) -> None:
        try:
            await self._do_stream()
        except Exception as e:
            self._add_system(f"⚠ Error: {e}")
        finally:
            self._streaming = False
            self._stream_bubble = None

    async def _do_stream(self) -> None:
        use_tools = model_supports_tools(self.current_model)
        tools     = TOOLS if (use_tools and self.mode == "build") else (
            [t for t in TOOLS if t["function"]["name"] in ("read_file","search_code")]
            if use_tools else None
        )

        # Build full message list with system prompt
        system_prompt = self.memory.build_system_prompt(
            global_prefs=self.glob_mem.read_md(),
            mode=self.mode,
        )
        messages = [{"role": "system", "content": system_prompt}]
        messages += self.memory.get_history(self.cfg.get("max_history", 20))

        # Add current user messages (skip first since it's in history)
        if self.history:
            messages.append(self.history[-1])

        full_text = ""

        async for item in self.provider.stream(messages, self.current_model, tools):
            if isinstance(item, str):
                full_text += item
                # Strip action blocks from display
                import re
                display = re.sub(r"```(?:action|ACTION)[\s\S]*?```", "", item, flags=re.IGNORECASE)
                if display and self._stream_bubble:
                    self._stream_bubble.append_text(display)
                    self._scroll_bottom()

            elif isinstance(item, dict) and "tool_call" in item:
                tc     = item["tool_call"]
                action = tool_call_to_action(tc["name"], tc["arguments"])
                if self.cfg.get("confirm_actions", True) and self.mode == "build":
                    self._add_action_card(action)
                else:
                    # Auto-apply
                    self._action_counter += 1
                    aid = self._action_counter
                    self.memory.log_action(action["action"], action.get("path",""), "auto-applying")
                    ok, msg = self._apply_action(action)
                    self.memory.log_action(action["action"], action.get("path",""), "success" if ok else "error")
                    self._add_system(f"{'✓' if ok else '✕'} {msg}")

        # Fallback: parse action blocks from text (non-tool models)
        if not use_tools and self.mode == "build":
            actions = parse_action_blocks(full_text)
            for action in actions:
                if self.cfg.get("confirm_actions", True):
                    self._add_action_card(action)
                else:
                    ok, msg = self._apply_action(action)
                    self._add_system(f"{'✓' if ok else '✕'} {msg}")

        # Save to memory
        self.memory.add_message("user", self.history[-1]["content"] if self.history else "", self.current_model)
        self.memory.add_message("assistant", full_text, self.current_model)
        self.history.append({"role": "assistant", "content": full_text})

    # ── Action execution ──────────────────────────────────────────────────────

    async def _execute_action(self, action_id: int) -> None:
        card = self.pending.get(action_id)
        if not card or card.resolved:
            return
        action = dict(card.action)
        # Use edited content if in edit mode
        if action.get("action") in ("create", "edit"):
            action["content"] = card.get_content()

        ok, message = self._apply_action(action)
        card.mark_done(ok, message)
        if action_id in self.pending:
            del self.pending[action_id]

    def _apply_action(self, action: dict) -> tuple[bool, str]:
        act     = action.get("action", "")
        path    = action.get("path", "")
        content = action.get("content") or ""
        try:
            match act:
                case "create" | "edit" | "upsert":
                    orig_p = Path(self.project_root) / path
                    if orig_p.exists():
                        self.memory.push_undo(path, orig_p.read_text(encoding="utf-8"))
                    r = self.executor.create(path, content)
                    self.memory.index_file(path, _detect_lang(path))
                    self.memory.log_action(act, path, "success")
                    return True, f"✓ {'Updated' if r.get('existed') else 'Created'} `{path}`"

                case "delete":
                    self.executor.delete(path)
                    self.memory.remove_file(path)
                    self.memory.log_action("delete", path, "success")
                    return True, f"✓ Deleted `{path}`"

                case "move":
                    dest = action.get("destination", "")
                    self.executor.move(path, dest)
                    self.memory.remove_file(path)
                    self.memory.index_file(dest, _detect_lang(dest))
                    self.memory.log_action("move", f"{path} → {dest}", "success")
                    return True, f"✓ Moved `{path}` → `{dest}`"

                case "mkdir":
                    self.executor.mkdir(path)
                    self.memory.log_action("mkdir", path, "success")
                    return True, f"✓ Created directory `{path}`"

                case "shell":
                    cmd = action.get("command", path)
                    r   = self.executor.shell(cmd)
                    self.memory.log_action("shell", cmd, "success" if r["ok"] else "error")
                    out = r["stdout"].strip() or r["stderr"].strip() or f"Exit {r['exit_code']}"
                    return r["ok"], f"$ {cmd}\n{out[:300]}"

                case "read":
                    r = self.executor.read(path)
                    ext = Path(path).suffix.lstrip(".")
                    self._add_system(f"**{path}**\n\n```{ext}\n{r['content'][:2000]}\n```")
                    return True, f"✓ Read `{path}`"

                case "search":
                    query   = action.get("query", path)
                    results = self.executor.search(query)
                    if not results:
                        self._add_system(f"No matches for `{query}`")
                    else:
                        lines = [f"**{len(results)} match(es) for `{query}`:**"]
                        for r in results[:15]:
                            lines.append(f"`{r['file']}:{r['line']}` — {r['content'].strip()}")
                        self._add_system("\n".join(lines))
                    return True, f"✓ Searched `{query}`"

                case _:
                    return False, f"Unknown action: {act}"

        except ActionError as e:
            self.memory.log_action(act, path, f"error: {e}")
            return False, f"✕ {e}"
        except Exception as e:
            return False, f"✕ Unexpected error: {e}"

    # ── Keybindings ───────────────────────────────────────────────────────────

    def action_toggle_mode(self) -> None:
        self.mode = "plan" if self.mode == "build" else "build"
        self._update_mode_ui()
        self._add_system(
            "◎ **Plan mode** — analysis only." if self.mode == "plan"
            else "▶ **Build mode** — full access."
        )

    def _update_mode_ui(self) -> None:
        try:
            btn = self.query_one("#mode-btn", Button)
            if self.mode == "plan":
                btn.label = "◎ PLAN"
                btn.add_class("plan")
            else:
                btn.label = "▶ BUILD"
                btn.remove_class("plan")
        except NoMatches:
            pass
        self.cfg["mode"] = self.mode
        save_config(self.cfg)

    def action_clear_chat(self) -> None:
        self.app.call_later(self._async_clear)

    async def _async_clear(self) -> None:
        self.memory.clear_history()
        self.history.clear()
        messages = self.query_one("#messages", Vertical)
        await messages.remove_children()
        self.pending.clear()
        self._add_system("◈ History cleared.")

    def action_show_tree(self) -> None:
        tree = self.memory.build_tree()
        self._add_system(f"```\n{tree}\n```")

    def action_open_prefs(self) -> None:
        prefs_path = Path.home() / ".echo" / "preferences.md"
        self._add_system(f"Edit preferences at: `{prefs_path}`")

    def action_pick_model(self) -> None:
        self._load_model_overlay()

    def action_close_overlay(self) -> None:
        try:
            overlay = self.query_one("#model-overlay")
            overlay.remove_class("visible")
        except NoMatches:
            pass

    @work(exclusive=True)
    async def _load_model_overlay(self) -> None:
        models = await self.provider.list_models()
        try:
            overlay   = self.query_one("#model-overlay")
            model_lst = self.query_one("#model-list", OptionList)
            model_lst.clear_options()
            for m in models:
                prefix = "⚡ " if model_supports_tools(m) else "  "
                model_lst.add_option(Option(f"{prefix}{m}", id=m))
            overlay.add_class("visible")
        except NoMatches:
            pass

    @on(OptionList.OptionSelected, "#model-list")
    def on_model_selected(self, event: OptionList.OptionSelected) -> None:
        model = event.option.id or ""
        if model:
            self.current_model = model
            self.cfg["model"]  = model
            save_config(self.cfg)
            self._update_model_label()
            self._add_system(f"✓ Model switched to `{model}` (history preserved)")
        self.action_close_overlay()


def _detect_lang(path: str) -> str:
    return {
        ".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript/React",
        ".js": "JavaScript", ".jsx": "JavaScript/React", ".json": "JSON",
        ".md": "Markdown", ".html": "HTML", ".css": "CSS", ".rs": "Rust",
        ".go": "Go", ".java": "Java", ".cpp": "C++", ".c": "C",
        ".sh": "Shell", ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML",
    }.get(Path(path).suffix.lower(), "")
