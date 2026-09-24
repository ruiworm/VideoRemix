"""Unified desktop, web, and CLI launcher for VideoRemix executables."""

import os
import sys


def main():
    # 1. Force Web UI if requested
    if "--web" in sys.argv:
        sys.argv.remove("--web")
        from videoremix.ui.web import main as web_main
        web_main()
        return

    # 2. If CLI parameters were explicitly provided
    cli_indicators = ["-i", "-o", "--preset", "-p", "--help", "-h", "--workers", "--zoom", "--speed"]
    if any(arg in sys.argv for arg in cli_indicators):
        from videoremix.cli import main as cli_main
        cli_main()
        return

    # 3. Default: Desktop GUI (Tkinter)
    try:
        from videoremix.ui.app import main as gui_main
        gui_main()
    except Exception as exc:
        print(f"[VideoRemix] Notice: Native GUI could not start ({exc}).")
        print("[VideoRemix] Launching resilient Web UI interface instead...")
        from videoremix.ui.web import main as web_main
        web_main()


if __name__ == "__main__":
    main()
