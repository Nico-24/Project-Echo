"""
File executor — all operations sandboxed to project root.
"""
import shutil
import subprocess
from pathlib import Path


class ActionError(Exception):
    pass


class Executor:
    def __init__(self, project_root: str):
        self.root = Path(project_root).resolve()

    def _safe(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if not str(p).startswith(str(self.root)):
            raise ActionError(f"Path '{rel}' escapes project root.")
        return p

    def create(self, path: str, content: str) -> dict:
        if not content or not content.strip():
            raise ActionError("Content cannot be empty.")
        target = self._safe(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        target.write_text(content, encoding="utf-8")
        return {"ok": True, "path": str(target.relative_to(self.root)), "existed": existed}

    def edit(self, path: str, content: str) -> dict:
        if not content or not content.strip():
            raise ActionError("Content cannot be empty.")
        target = self._safe(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"ok": True, "path": str(target.relative_to(self.root))}

    def delete(self, path: str) -> dict:
        target = self._safe(path)
        if not target.exists():
            raise ActionError(f"'{path}' does not exist.")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return {"ok": True, "path": str(target.relative_to(self.root))}

    def move(self, path: str, destination: str) -> dict:
        src = self._safe(path)
        dst = self._safe(destination)
        if not src.exists():
            raise ActionError(f"'{path}' does not exist.")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            dst.unlink() if dst.is_file() else shutil.rmtree(dst)
        shutil.move(str(src), str(dst))
        return {"ok": True, "from": str(src.relative_to(self.root)), "to": str(dst.relative_to(self.root))}

    def mkdir(self, path: str) -> dict:
        target = self._safe(path)
        target.mkdir(parents=True, exist_ok=True)
        return {"ok": True, "path": str(target.relative_to(self.root))}

    def read(self, path: str) -> dict:
        target = self._safe(path)
        if not target.exists():
            raise ActionError(f"'{path}' does not exist.")
        return {"ok": True, "path": str(target.relative_to(self.root)), "content": target.read_text(encoding="utf-8")}

    def shell(self, command: str) -> dict:
        try:
            result = subprocess.run(command, shell=True, cwd=str(self.root),
                                    capture_output=True, text=True, timeout=60)
            return {"ok": result.returncode == 0, "stdout": result.stdout,
                    "stderr": result.stderr, "exit_code": result.returncode}
        except subprocess.TimeoutExpired:
            return {"ok": False, "stdout": "", "stderr": "Timed out after 60s.", "exit_code": -1}

    def search(self, query: str, pattern: str = "*") -> list[dict]:
        import re
        results = []
        try:
            regex = re.compile(re.escape(query), re.IGNORECASE)
        except re.error:
            return []
        EXCLUDED = {"node_modules", "__pycache__", ".git", ".echo", "out", "dist"}
        glob = f"**/{pattern}" if "/" not in pattern else pattern
        for f in sorted(self.root.glob(glob)):
            if not f.is_file():
                continue
            if any(p in EXCLUDED for p in f.relative_to(self.root).parts):
                continue
            try:
                for i, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                    if regex.search(line):
                        results.append({"file": str(f.relative_to(self.root)), "line": i, "content": line[:200]})
                        if len(results) >= 40:
                            return results
            except Exception:
                continue
        return results
