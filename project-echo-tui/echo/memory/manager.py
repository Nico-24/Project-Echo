"""
Dual-layer memory system.
  ~/.echo/preferences.md  — global user preferences (editable)
  ~/.echo/global.db        — cross-project session log
  <project>/.echo/memory.md — project-specific context (editable)
  <project>/.echo/memory.db — project history, file index, decisions, undo stack
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path


# ── Project memory ────────────────────────────────────────────────────────────

class ProjectMemory:
    def __init__(self, project_root: str):
        self.root    = Path(project_root).resolve()
        self.dir     = self.root / ".echo"
        self.dir.mkdir(exist_ok=True)
        self.db_path = self.dir / "memory.db"
        self.md_path = self.dir / "memory.md"
        self._init_db()
        self._init_md()

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    role    TEXT NOT NULL,
                    content TEXT NOT NULL,
                    model   TEXT,
                    ts      TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS file_index (
                    path     TEXT PRIMARY KEY,
                    language TEXT,
                    updated  TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS facts (
                    key     TEXT PRIMARY KEY,
                    value   TEXT NOT NULL,
                    updated TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS action_log (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    action  TEXT NOT NULL,
                    path    TEXT,
                    status  TEXT NOT NULL,
                    ts      TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS undo_stack (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    path    TEXT NOT NULL,
                    content TEXT NOT NULL,
                    ts      TEXT DEFAULT (datetime('now'))
                );
            """)

    def _init_md(self):
        if not self.md_path.exists():
            self.md_path.write_text(
                "# Project Echo — Project Memory\n\n"
                "> Edit freely. Echo reads this before every message.\n\n"
                "## Project overview\n\n_Describe the project._\n\n"
                "## Stack & conventions\n\n_Languages, frameworks, naming rules._\n\n"
                "## Goals\n\n_Current objectives._\n",
                encoding="utf-8",
            )

    # Conversations
    def add_message(self, role: str, content: str, model: str = "") -> None:
        with self._conn() as c:
            c.execute("INSERT INTO conversations (role,content,model) VALUES (?,?,?)", (role,content,model))

    def get_history(self, limit: int = 20) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT role,content FROM conversations ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{"role": r, "content": t} for r, t in reversed(rows)]

    def clear_history(self):
        with self._conn() as c:
            c.execute("DELETE FROM conversations")

    # File index
    def index_file(self, path: str, language: str = "") -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO file_index(path,language,updated) VALUES(?,?,datetime('now')) "
                "ON CONFLICT(path) DO UPDATE SET language=excluded.language,updated=excluded.updated",
                (path, language),
            )

    def remove_file(self, path: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM file_index WHERE path=?", (path,))

    def get_file_index(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT path,language,updated FROM file_index ORDER BY path").fetchall()
        return [{"path": p, "language": l, "updated": u} for p, l, u in rows]

    # Facts
    def set_fact(self, key: str, value: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO facts(key,value,updated) VALUES(?,?,datetime('now')) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated",
                (key, value),
            )

    def get_facts(self) -> dict:
        with self._conn() as c:
            rows = c.execute("SELECT key,value FROM facts").fetchall()
        return dict(rows)

    # Action log
    def log_action(self, action: str, path: str, status: str) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO action_log(action,path,status) VALUES(?,?,?)", (action,path,status))

    def get_recent_actions(self, limit: int = 10) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT action,path,status,ts FROM action_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{"action": a, "path": p, "status": s, "ts": t} for a, p, s, t in rows]

    # Undo stack
    def push_undo(self, path: str, content: str) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO undo_stack(path,content) VALUES(?,?)", (path, content))

    def pop_undo(self) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT id,path,content FROM undo_stack ORDER BY id DESC LIMIT 1").fetchone()
            if not row:
                return None
            c.execute("DELETE FROM undo_stack WHERE id=?", (row[0],))
            return {"path": row[1], "content": row[2]}

    # memory.md
    def read_md(self) -> str:
        return self.md_path.read_text(encoding="utf-8") if self.md_path.exists() else ""

    def write_md(self, content: str) -> None:
        self.md_path.write_text(content, encoding="utf-8")

    # Project tree
    def build_tree(self, max_depth: int = 3) -> str:
        EXCLUDED = {"node_modules","__pycache__",".git",".echo","out","dist","venv",".env"}
        lines = [self.root.name + "/"]
        def walk(directory: Path, prefix: str, depth: int):
            if depth > max_depth:
                return
            try:
                entries = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            except PermissionError:
                return
            visible = [e for e in entries if e.name not in EXCLUDED and not e.name.startswith(".")]
            for i, entry in enumerate(visible[:40]):
                conn = "└── " if i == len(visible) - 1 else "├── "
                lines.append(f"{prefix}{conn}{entry.name}{'/' if entry.is_dir() else ''}")
                if entry.is_dir():
                    ext = "    " if i == len(visible) - 1 else "│   "
                    walk(entry, prefix + ext, depth + 1)
        walk(self.root, "", 1)
        return "\n".join(lines)

    # System prompt
    def build_system_prompt(self, global_prefs: str = "", mode: str = "build") -> str:
        parts = []
        md = self.read_md().strip()
        if md:
            parts.append(f"## Project memory\n\n{md}")
        files = self.get_file_index()
        if files:
            fl = "\n".join(f"  - `{f['path']}` ({f['language']})" for f in files[:30])
            parts.append(f"## Known files\n\n{fl}")
        facts = self.get_facts()
        if facts:
            fl = "\n".join(f"  - **{k}**: {v}" for k, v in facts.items())
            parts.append(f"## Project facts\n\n{fl}")
        actions = self.get_recent_actions(5)
        if actions:
            al = "\n".join(f"  - {a['action']} `{a['path']}` → {a['status']}" for a in actions)
            parts.append(f"## Recent actions\n\n{al}")

        # Base instructions — minimal, tool-call oriented
        base = (
            "You are Project Echo, an AI coding assistant running in the terminal.\n"
            "You have tools to create, edit, delete files, run commands, read files, and search code.\n"
            "Always explain what you will do before calling a tool.\n"
        )
        if mode == "plan":
            base += "PLAN MODE: describe what you would do, do NOT call file-writing tools.\n"
        if global_prefs:
            parts.insert(0, f"## User preferences\n\n{global_prefs}")
        if parts:
            return base + "\n\n---\n\n" + "\n\n---\n\n".join(parts)
        return base


# ── Global memory ─────────────────────────────────────────────────────────────

class GlobalMemory:
    def __init__(self):
        self.dir     = Path.home() / ".echo"
        self.dir.mkdir(exist_ok=True)
        self.md_path = self.dir / "preferences.md"
        self.db_path = self.dir / "global.db"
        self._init_db()
        self._init_md()

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    project TEXT,
                    summary TEXT,
                    facts   TEXT,
                    ts      TEXT DEFAULT (datetime('now'))
                );
            """)

    def _init_md(self):
        if not self.md_path.exists():
            self.md_path.write_text(
                "# Project Echo — Global Preferences\n\n"
                "> Applies to all projects.\n\n"
                "## My coding style\n\n_Naming conventions, formatting preferences._\n\n"
                "## Tools I always use\n\n_Default languages and frameworks._\n\n"
                "## Things Echo should never do\n\n_Hard rules._\n",
                encoding="utf-8",
            )

    def read_md(self) -> str:
        return self.md_path.read_text(encoding="utf-8") if self.md_path.exists() else ""

    def log_session(self, project: str, summary: str, facts: list[str]) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO sessions(project,summary,facts) VALUES(?,?,?)",
                (project, summary, json.dumps(facts)),
            )

    def get_recent_sessions(self, limit: int = 5) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT project,summary,facts,ts FROM sessions ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{"project": p, "summary": s, "facts": json.loads(f or "[]"), "ts": t}
                for p, s, f, t in rows]
