"""Dual memory system for Project Echo.

ProjectMemory : per-project SQLite db (.echo/memory.db) + human-readable
                markdown mirror (.echo/memory.md).
GlobalMemory  : cross-project preferences (~/.echo/preferences.md) and a
                session log (~/.echo/global.db).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

IGNORED_DIRS = {
    ".git", ".echo", ".hg", ".svn", "__pycache__", "node_modules",
    ".venv", "venv", "env", ".mypy_cache", ".pytest_cache", ".tox",
    "dist", "build", ".idea", ".vscode",
}


def _now() -> float:
    return time.time()


GLOBAL_SKILLS_DIR = Path.home() / ".echo" / "skills"


def parse_skill_frontmatter(content: str) -> dict:
    """Parse the YAML frontmatter block of a SKILL.md (simple key: value pairs)."""
    meta: dict[str, str] = {}
    if not content or not content.lstrip().startswith("---"):
        return meta
    text = content.lstrip()
    end = text.find("\n---", 3)
    if end == -1:
        return meta
    for line in text[3:end].splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() and not key.startswith(" "):
            meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta


def strip_skill_frontmatter(content: str) -> str:
    """Return the markdown body of a SKILL.md, without the frontmatter block."""
    text = content.lstrip()
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:].lstrip("\n")
    return content


class ProjectMemory:
    """Per-project memory: conversations, file index, facts, actions, undo stack."""

    def __init__(self, project_root: str | Path):
        self.root = Path(project_root).resolve()
        self.dir = self.root / ".echo"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.dir / "memory.db"
        self.md_path = self.dir / "memory.md"
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    ts REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS file_index (
                    path TEXT PRIMARY KEY,
                    summary TEXT NOT NULL DEFAULT '',
                    ts REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS facts (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    ts REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS action_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_type TEXT NOT NULL,
                    path TEXT NOT NULL DEFAULT '',
                    detail TEXT NOT NULL DEFAULT '',
                    ts REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS undo_stack (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_json TEXT NOT NULL,
                    ts REAL NOT NULL
                );
                """
            )
            self._conn.commit()

    # ------------------------------------------------------------------ #
    # Conversations
    # ------------------------------------------------------------------ #

    def add_message(self, role: str, content: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO conversations (role, content, ts) VALUES (?, ?, ?)",
                (role, content, _now()),
            )
            self._conn.commit()

    def get_history(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content, ts FROM conversations ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def clear_history(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM conversations")
            self._conn.commit()

    # ------------------------------------------------------------------ #
    # File index
    # ------------------------------------------------------------------ #

    def index_file(self, path: str, summary: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO file_index (path, summary, ts) VALUES (?, ?, ?) "
                "ON CONFLICT(path) DO UPDATE SET summary=excluded.summary, ts=excluded.ts",
                (path, summary, _now()),
            )
            self._conn.commit()

    def remove_file(self, path: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM file_index WHERE path = ?", (path,))
            self._conn.commit()

    def get_file_index(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT path, summary, ts FROM file_index ORDER BY path"
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Facts
    # ------------------------------------------------------------------ #

    def set_fact(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO facts (key, value, ts) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, ts=excluded.ts",
                (key, value, _now()),
            )
            self._conn.commit()
        self._sync_md()

    def get_facts(self) -> dict[str, str]:
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM facts ORDER BY key").fetchall()
        return {r["key"]: r["value"] for r in rows}

    # ------------------------------------------------------------------ #
    # Action log + undo stack
    # ------------------------------------------------------------------ #

    def log_action(self, action_type: str, path: str = "", detail: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO action_log (action_type, path, detail, ts) VALUES (?, ?, ?, ?)",
                (action_type, path, detail[:2000], _now()),
            )
            self._conn.commit()

    def get_recent_actions(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT action_type, path, detail, ts FROM action_log "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def push_undo(self, action: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO undo_stack (action_json, ts) VALUES (?, ?)",
                (json.dumps(action), _now()),
            )
            self._conn.commit()

    def pop_undo(self) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, action_json FROM undo_stack ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            self._conn.execute("DELETE FROM undo_stack WHERE id = ?", (row["id"],))
            self._conn.commit()
        try:
            return json.loads(row["action_json"])
        except json.JSONDecodeError:
            return None

    # ------------------------------------------------------------------ #
    # Project tree + system prompt
    # ------------------------------------------------------------------ #

    def build_tree(self, max_depth: int = 3) -> str:
        """Render an indented tree of the project (ignoring noise dirs)."""
        lines: list[str] = [self.root.name + "/"]
        self._tree_walk(self.root, "", 1, max_depth, lines)
        return "\n".join(lines)

    def _tree_walk(
        self, folder: Path, prefix: str, depth: int, max_depth: int, lines: list[str]
    ) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(
                (e for e in folder.iterdir() if e.name not in IGNORED_DIRS),
                key=lambda e: (not e.is_dir(), e.name.lower()),
            )
        except OSError:
            return
        entries = entries[:80]  # keep huge folders sane
        for i, entry in enumerate(entries):
            connector = "└─ " if i == len(entries) - 1 else "├─ "
            suffix = "/" if entry.is_dir() else ""
            lines.append(prefix + connector + entry.name + suffix)
            if entry.is_dir():
                extension = "   " if i == len(entries) - 1 else "│  "
                self._tree_walk(entry, prefix + extension, depth + 1, max_depth, lines)

    def count_files(self) -> int:
        count = 0
        stack = [self.root]
        while stack:
            current = stack.pop()
            try:
                for entry in current.iterdir():
                    if entry.is_dir():
                        if entry.name not in IGNORED_DIRS:
                            stack.append(entry)
                    else:
                        count += 1
            except OSError:
                continue
        return count

    def build_system_prompt(self, global_prefs: str = "", mode: str = "build") -> str:
        facts = self.get_facts()
        tree = self.build_tree(max_depth=3)

        parts = [
            "You are Echo, a coding assistant working inside the user's project "
            f"'{self.root.name}'. Be concise and practical.",
            "",
            "## Project structure",
            "```",
            tree[:4000],
            "```",
        ]

        if facts:
            parts += ["", "## Known facts about this project"]
            parts += [f"- {k}: {v}" for k, v in list(facts.items())[:30]]

        recent = self.get_recent_actions(limit=8)
        if recent:
            parts += ["", "## Recent actions"]
            parts += [f"- {a['action_type']} {a['path']}".rstrip() for a in recent]

        if global_prefs.strip():
            parts += ["", "## User preferences", global_prefs.strip()[:2000]]

        if mode == "plan":
            parts += [
                "",
                "## Mode: PLAN",
                "You are in PLAN mode. Discuss, analyze, and design freely. "
                "Do NOT suggest or attempt any file operations. "
                "The user will switch to Build mode when ready to implement. "
                "All conversation is saved and will be available in Build mode.",
            ]
        else:
            parts += [
                "",
                "## Mode: BUILD",
                "You may modify the project using your tools. Prefer small, focused "
                "changes and explain what you are doing.",
                "",
                "If native tool calling is unavailable to you, request file operations "
                "by emitting fenced action blocks, one JSON object per block:",
                "```action",
                '{"type": "create", "path": "src/app.py", "content": "...", '
                '"description": "what this does"}',
                "```",
                'Valid types: "create", "edit", "delete", "move" (needs "dest"), '
                '"mkdir", "shell" (needs "command").',
                'For "create" and "edit", "content" must be the COMPLETE file content.',
            ]

        return "\n".join(parts)

    # ------------------------------------------------------------------ #
    # Skills (Claude Code compatible: <folder>/SKILL.md with frontmatter)
    # ------------------------------------------------------------------ #

    @property
    def project_skills_dir(self) -> Path:
        return self.dir / "skills"

    def list_skills(self) -> list[dict]:
        """All available skills; project skills override global ones by name."""
        found: dict[str, dict] = {}
        for source, base in (
            ("global", GLOBAL_SKILLS_DIR),
            ("project", self.project_skills_dir),
        ):
            if not base.is_dir():
                continue
            for folder in sorted(base.iterdir()):
                skill_md = folder / "SKILL.md"
                if not (folder.is_dir() and skill_md.is_file()):
                    continue
                try:
                    content = skill_md.read_text(encoding="utf-8")
                except OSError:
                    continue
                meta = parse_skill_frontmatter(content)
                name = meta.get("name", folder.name)
                found[name] = {
                    "name": name,
                    "description": meta.get("description", ""),
                    "source": source,
                    "path": str(skill_md),
                }
        return sorted(found.values(), key=lambda s: s["name"])

    def load_skill(self, name: str) -> str:
        """Full SKILL.md content for a skill (project dir wins over global)."""
        for base in (self.project_skills_dir, GLOBAL_SKILLS_DIR):
            skill_md = base / name / "SKILL.md"
            if skill_md.is_file():
                try:
                    return skill_md.read_text(encoding="utf-8")
                except OSError:
                    return ""
        # Folder name may differ from the frontmatter name: fall back to a scan.
        for skill in self.list_skills():
            if skill["name"] == name:
                try:
                    return Path(skill["path"]).read_text(encoding="utf-8")
                except OSError:
                    return ""
        return ""

    def load_active_skills(self, active_names: list[str]) -> str:
        """Concatenate the bodies of all active skills, global ones first
        (project skills load after, so they take precedence)."""
        if not active_names:
            return ""
        infos = {s["name"]: s for s in self.list_skills()}
        ordered = (
            sorted(n for n in active_names if infos.get(n, {}).get("source") == "global")
            + sorted(n for n in active_names if infos.get(n, {}).get("source") == "project")
        )
        blocks = []
        for name in ordered:
            body = strip_skill_frontmatter(self.load_skill(name)).strip()
            if body:
                blocks.append(f"### Skill: {name}\n{body}")
        if not blocks:
            return ""
        return (
            "# Active skills\n"
            "Follow the instructions of every active skill below.\n\n"
            + "\n\n".join(blocks)
        )

    def save_skill(self, name: str, content: str, global_: bool = False) -> Path:
        """Write a SKILL.md under the project (default) or global skills dir."""
        base = GLOBAL_SKILLS_DIR if global_ else self.project_skills_dir
        folder = base / name
        folder.mkdir(parents=True, exist_ok=True)
        skill_md = folder / "SKILL.md"
        skill_md.write_text(content, encoding="utf-8")
        return skill_md

    # ------------------------------------------------------------------ #
    # Markdown mirror
    # ------------------------------------------------------------------ #

    def _sync_md(self) -> None:
        facts = self.get_facts()
        actions = self.get_recent_actions(limit=15)
        lines = [f"# Echo memory - {self.root.name}", ""]
        if facts:
            lines += ["## Facts", ""]
            lines += [f"- **{k}**: {v}" for k, v in facts.items()]
            lines.append("")
        if actions:
            lines += ["## Recent actions", ""]
            for a in actions:
                stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(a["ts"]))
                lines.append(f"- `{stamp}` {a['action_type']} {a['path']}".rstrip())
            lines.append("")
        try:
            self.md_path.write_text("\n".join(lines), encoding="utf-8")
        except OSError:
            pass

    def save_snapshot(self) -> None:
        """Refresh the markdown mirror (call after each exchange)."""
        self._sync_md()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class GlobalMemory:
    """Cross-project memory in ~/.echo: preferences.md + session log in global.db."""

    def __init__(self):
        self.dir = Path.home() / ".echo"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.md_path = self.dir / "preferences.md"
        self.db_path = self.dir / "global.db"
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    ts REAL NOT NULL
                )
                """
            )
            self._conn.commit()

    def read_md(self) -> str:
        try:
            if self.md_path.exists():
                return self.md_path.read_text(encoding="utf-8")
        except OSError:
            pass
        return ""

    def log_session(self, project: str, summary: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions (project, summary, ts) VALUES (?, ?, ?)",
                (project, summary[:2000], _now()),
            )
            self._conn.commit()

    def get_recent_sessions(self, limit: int = 10) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT project, summary, ts FROM sessions ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
