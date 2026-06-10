"""
Project Echo — entry point.
Run with: echo  (from any project folder)
"""
import sys
import os
from pathlib import Path


def main():
    # Use current directory as project root
    project_root = str(Path.cwd().resolve())

    # Quick args
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg in ("-h", "--help"):
            print("Project Echo — Local AI coding assistant")
            print()
            print("Usage:")
            print("  echo              Launch in current directory")
            print("  echo <path>       Launch in specified directory")
            print("  echo --version    Show version")
            print()
            print("Inside Echo:")
            print("  /help             Show all commands")
            print("  Ctrl+S            Switch model")
            print("  Ctrl+M            Toggle Plan/Build mode")
            print("  Ctrl+L            Clear chat")
            print("  Ctrl+C            Quit")
            return
        if arg in ("-v", "--version"):
            print("Project Echo 1.0.0")
            return
        if not arg.startswith("-"):
            p = Path(arg)
            if p.is_dir():
                project_root = str(p.resolve())
            else:
                print(f"Error: '{arg}' is not a directory.")
                sys.exit(1)

    # Check Python version
    if sys.version_info < (3, 10):
        print("Project Echo requires Python 3.10 or later.")
        sys.exit(1)

    from echo.ui.app import EchoApp
    app = EchoApp(project_root)
    app.run()


if __name__ == "__main__":
    main()
