"""Install skills from GitHub repositories using only httpx (no git needed).

Skill discovery uses the GitHub trees API:
    GET https://api.github.com/repos/<owner>/<repo>/git/trees/<ref>?recursive=1
then each SKILL.md is fetched from raw.githubusercontent.com and saved to
<dest>/<skill-name>/SKILL.md alongside an echo-meta.json recording the source.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Callable

import httpx

API_TIMEOUT = httpx.Timeout(30.0)

_GITHUB_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/"
    r"([^/\s]+)/([^/\s]+?)(?:\.git)?"
    r"(?:/(?:tree|blob)/([^/\s]+)(?:/(.+))?)?/?$"
)


class InstallError(Exception):
    """Raised when a skill installation fails."""


def parse_github_url(url: str) -> tuple[str, str, str, str]:
    """Parse a GitHub URL into (owner, repo, ref, subpath).

    Accepts plain repo URLs and /tree/<branch>/<folder> URLs.
    ref defaults to HEAD when the URL names no branch.
    """
    match = _GITHUB_URL_RE.match(url.strip())
    if not match:
        raise InstallError(f"Not a GitHub repository URL: {url}")
    owner, repo, ref, subpath = match.groups()
    return owner, repo, ref or "HEAD", (subpath or "").rstrip("/")


async def install_skills_from_github(
    url: str,
    dest_dir: Path,
    progress: Callable[[str], None],
) -> tuple[int, int]:
    """Find every SKILL.md under *url* and install it into *dest_dir*.

    Calls *progress* with display lines as work happens.
    Returns (installed, total_found).
    """
    owner, repo, ref, subpath = parse_github_url(url)
    progress(f"Installing skills from github.com/{owner}/{repo}...")

    api = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{ref}?recursive=1"
    async with httpx.AsyncClient(timeout=API_TIMEOUT, follow_redirects=True) as client:
        try:
            response = await client.get(
                api, headers={"Accept": "application/vnd.github+json"}
            )
        except httpx.HTTPError as exc:
            raise InstallError(f"Could not reach the GitHub API: {exc}") from exc
        if response.status_code == 404:
            raise InstallError(f"Repository or ref not found: {owner}/{repo}@{ref}")
        if response.status_code != 200:
            raise InstallError(f"GitHub API returned HTTP {response.status_code}")

        entries = response.json().get("tree", [])
        skill_paths = [
            e["path"] for e in entries
            if e.get("type") == "blob" and e["path"].split("/")[-1] == "SKILL.md"
        ]
        if subpath:
            skill_paths = [
                p for p in skill_paths
                if p == f"{subpath}/SKILL.md" or p.startswith(f"{subpath}/")
            ]

        if not skill_paths:
            progress("✗ no SKILL.md files found at that URL")
            return 0, 0

        installed = 0
        meta = json.dumps(
            {"source": url, "installed": time.strftime("%Y-%m-%d")}, indent=2
        )
        for path in skill_paths:
            parts = path.split("/")
            name = parts[-2] if len(parts) >= 2 else repo
            raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
            try:
                file_response = await client.get(raw)
                if file_response.status_code != 200:
                    raise InstallError(f"HTTP {file_response.status_code}")
                content = file_response.text
                if not content.strip():
                    raise InstallError("empty file")
                folder = dest_dir / name
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "SKILL.md").write_text(content, encoding="utf-8")
                (folder / "echo-meta.json").write_text(meta, encoding="utf-8")
                installed += 1
                progress(f"✓ {name}")
            except (httpx.HTTPError, InstallError, OSError) as exc:
                progress(f"✗ {name} ({exc})")

        progress(f"Installed {installed} of {len(skill_paths)} skills")
        return installed, len(skill_paths)


def collect_sources(skill_dirs: list[Path]) -> list[tuple[str, Path]]:
    """Unique (source_url, skills_base_dir) pairs from installed echo-meta.json
    files — the inputs needed to re-run installation for /skill update."""
    pairs: list[tuple[str, Path]] = []
    seen: set[tuple[str, str]] = set()
    for base in skill_dirs:
        if not base.is_dir():
            continue
        for folder in sorted(base.iterdir()):
            meta_file = folder / "echo-meta.json"
            if not (folder.is_dir() and meta_file.is_file()):
                continue
            try:
                source = json.loads(meta_file.read_text(encoding="utf-8")).get("source")
            except (OSError, json.JSONDecodeError):
                continue
            if source and (source, str(base)) not in seen:
                seen.add((source, str(base)))
                pairs.append((source, base))
    return pairs
