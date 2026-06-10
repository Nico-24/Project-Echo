"""Sandboxed file/shell operations for Project Echo.

Every path is resolved and verified to live inside the project root, so the
model can never touch files outside the project (no `..` traversal, no
absolute paths pointing elsewhere).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

# Directories never touched by search() or considered interesting.
IGNORED_DIRS = {
    ".git", ".echo", ".hg", ".svn", "__pycache__", "node_modules",
    ".venv", "venv", "env", ".mypy_cache", ".pytest_cache", ".tox",
    "dist", "build", ".idea", ".vscode",
}

TEXT_EXTENSIONS = {
    ".py", ".pyw", ".txt", ".md", ".rst", ".json", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".html", ".htm", ".css", ".scss", ".js", ".jsx", ".ts",
    ".tsx", ".vue", ".c", ".h", ".cpp", ".hpp", ".cs", ".java", ".kt", ".go",
    ".rs", ".rb", ".php", ".sh", ".bat", ".ps1", ".sql", ".xml", ".csv",
    ".env", ".gitignore", ".dockerignore", ".editorconfig", ".lua", ".r",
}

MAX_READ_BYTES = 512 * 1024
MAX_SEARCH_RESULTS = 200


class ActionError(Exception):
    """Raised when an action is invalid or unsafe."""


class Executor:
    """Performs file operations and shell commands sandboxed to a project root."""

    def __init__(self, project_root: str | Path):
        self.root = Path(project_root).resolve()
        if not self.root.is_dir():
            raise ActionError(f"Project root is not a directory: {self.root}")

    # ------------------------------------------------------------------ #
    # Path handling
    # ------------------------------------------------------------------ #

    def _resolve(self, path: str | Path) -> Path:
        """Resolve *path* and guarantee it lives inside the project root."""
        if path is None or not str(path).strip():
            raise ActionError("Path is empty.")
        raw = Path(str(path).strip().strip('"').strip("'"))
        candidate = raw if raw.is_absolute() else self.root / raw
        try:
            resolved = candidate.resolve()
        except OSError as exc:  # malformed path on Windows (e.g. bad chars)
            raise ActionError(f"Invalid path: {path} ({exc})") from exc
        try:
            resolved.relative_to(self.root)
        except ValueError:
            raise ActionError(f"Path escapes the project root: {path}") from None
        return resolved

    def rel(self, path: Path) -> str:
        """Pretty project-relative path for display."""
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return str(path)

    # ------------------------------------------------------------------ #
    # File operations
    # ------------------------------------------------------------------ #

    def create(self, path: str, content: str) -> str:
        if content is None or not str(content).strip():
            raise ActionError("Refusing to create a file with empty content.")
        target = self._resolve(path)
        if target.is_dir():
            raise ActionError(f"A directory already exists at: {self.rel(target)}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding="utf-8")
        return f"Created {self.rel(target)} ({len(content)} chars)"

    def edit(self, path: str, content: str) -> str:
        if content is None or not str(content).strip():
            raise ActionError("Refusing to write empty content. Use delete instead.")
        target = self._resolve(path)
        if not target.exists():
            raise ActionError(f"File does not exist: {self.rel(target)} (use create)")
        if target.is_dir():
            raise ActionError(f"Cannot edit a directory: {self.rel(target)}")
        target.write_text(str(content), encoding="utf-8")
        return f"Edited {self.rel(target)} ({len(content)} chars)"

    def delete(self, path: str) -> str:
        target = self._resolve(path)
        if target == self.root:
            raise ActionError("Refusing to delete the project root.")
        if not target.exists():
            raise ActionError(f"Path does not exist: {self.rel(target)}")
        if target.is_dir():
            shutil.rmtree(target)
            return f"Deleted directory {self.rel(target)}"
        target.unlink()
        return f"Deleted {self.rel(target)}"

    def move(self, path: str, dest: str) -> str:
        source = self._resolve(path)
        target = self._resolve(dest)
        if not source.exists():
            raise ActionError(f"Source does not exist: {self.rel(source)}")
        if target.exists():
            raise ActionError(f"Destination already exists: {self.rel(target)}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        return f"Moved {self.rel(source)} -> {self.rel(target)}"

    def mkdir(self, path: str) -> str:
        target = self._resolve(path)
        if target.is_file():
            raise ActionError(f"A file already exists at: {self.rel(target)}")
        target.mkdir(parents=True, exist_ok=True)
        return f"Created directory {self.rel(target)}"

    def read(self, path: str) -> str:
        target = self._resolve(path)
        if not target.exists():
            raise ActionError(f"File does not exist: {self.rel(target)}")
        if target.is_dir():
            entries = sorted(p.name + ("/" if p.is_dir() else "") for p in target.iterdir())
            return "\n".join(entries) if entries else "(empty directory)"
        if target.stat().st_size > MAX_READ_BYTES:
            raise ActionError(
                f"File too large to read ({target.stat().st_size} bytes): {self.rel(target)}"
            )
        try:
            return target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ActionError(f"Could not read {self.rel(target)}: {exc}") from exc

    # ------------------------------------------------------------------ #
    # Shell + search
    # ------------------------------------------------------------------ #

    def shell(self, command: str) -> str:
        if not command or not command.strip():
            raise ActionError("Command is empty.")
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            raise ActionError(f"Command timed out after 60s: {command}") from None
        except OSError as exc:
            raise ActionError(f"Could not run command: {exc}") from exc

        parts = []
        if proc.stdout and proc.stdout.strip():
            parts.append(proc.stdout.rstrip())
        if proc.stderr and proc.stderr.strip():
            parts.append("[stderr]\n" + proc.stderr.rstrip())
        parts.append(f"[exit code: {proc.returncode}]")
        return "\n".join(parts)

    def search(self, query: str) -> str:
        if not query or not query.strip():
            raise ActionError("Search query is empty.")
        needle = query.lower()
        results: list[str] = []
        for file in self._iter_text_files():
            try:
                text = file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if needle in line.lower():
                    results.append(f"{self.rel(file)}:{lineno}: {line.strip()[:200]}")
                    if len(results) >= MAX_SEARCH_RESULTS:
                        results.append(f"... (stopped at {MAX_SEARCH_RESULTS} matches)")
                        return "\n".join(results)
        if not results:
            return f"No matches for: {query}"
        return "\n".join(results)

    def _iter_text_files(self):
        stack = [self.root]
        while stack:
            current = stack.pop()
            try:
                entries = sorted(current.iterdir())
            except OSError:
                continue
            for entry in entries:
                if entry.is_dir():
                    if entry.name not in IGNORED_DIRS and not entry.name.startswith("."):
                        stack.append(entry)
                elif entry.suffix.lower() in TEXT_EXTENSIONS or entry.name in TEXT_EXTENSIONS:
                    if entry.stat().st_size <= MAX_READ_BYTES:
                        yield entry

    # ------------------------------------------------------------------ #
    # Action dispatch (used by the UI)
    # ------------------------------------------------------------------ #

    def apply(self, action: dict) -> str:
        """Execute an action dict ({"type": ..., "path": ..., ...}) and return a result message."""
        kind = action.get("type", "")
        path = action.get("path", "")
        if kind == "create":
            return self.create(path, action.get("content", ""))
        if kind == "edit":
            return self.edit(path, action.get("content", ""))
        if kind == "delete":
            return self.delete(path)
        if kind == "move":
            return self.move(path, action.get("dest", ""))
        if kind == "mkdir":
            return self.mkdir(path)
        if kind == "read":
            return self.read(path)
        if kind == "shell":
            return self.shell(action.get("command", "") or path)
        if kind == "search":
            return self.search(action.get("query", "") or path)
        raise ActionError(f"Unknown action type: {kind!r}")
