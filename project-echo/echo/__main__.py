"""Entry point for Project Echo: `python -m echo` or the `echo` console script."""

import sys
from pathlib import Path

from echo import __app_name__, __version__

USAGE = f"""\
{__app_name__} v{__version__} - terminal UI coding assistant

Usage:
  pe [PROJECT_ROOT]        Launch Echo in PROJECT_ROOT (default: current dir)
  pe --version             Show version
  pe --help                Show this help

Aliases: pecho, project-echo (same as pe). `python -m echo` also works.

Keyboard:
  Ctrl+M  toggle Build/Plan mode      Ctrl+S  model picker
  Ctrl+L  clear conversation          Ctrl+T  project tree
  Ctrl+C  quit

Slash commands:
  /help /tree /read <path> /search <text> /run <cmd> /clear
  /memory /plan /build /models /model <name> /undo /prefs
  /skills [active] /skill <name> /skill off [name]
  /skill save [--global] <name> /skill install <url> [--project]
  /skill uninstall <name> /skill update
  /config [<key> [<value>]]
"""


def main() -> int:
    args = sys.argv[1:]

    if "--help" in args or "-h" in args:
        print(USAGE)
        return 0
    if "--version" in args or "-V" in args:
        print(f"{__app_name__} v{__version__}")
        return 0

    if args:
        root = Path(args[0]).expanduser().resolve()
        if not root.exists():
            print(f"error: project root does not exist: {root}", file=sys.stderr)
            return 1
        if not root.is_dir():
            print(f"error: project root is not a directory: {root}", file=sys.stderr)
            return 1
    else:
        root = Path.cwd()

    from echo.ui.app import EchoApp

    EchoApp(project_root=root).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
