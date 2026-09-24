"""Unified desktop, web, and CLI launcher for VideoRemix executables."""

import os
import sys


def setup_windows_dpi_awareness():
    """Configure Windows high-DPI awareness before creating Tk instance."""
    if sys.platform.startswith("win") or (os.name == "nt"):
        try:
            import ctypes
            # 1. Per-Monitor V2 (Windows 10 Creators Update 1703+)
            try:
                if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
                    return
            except Exception:
                pass

            # 2. System DPI Aware (Windows 8.1+)
            try:
                if ctypes.windll.shcore.SetProcessDpiAwareness(1) == 0:
                    return
            except Exception:
                pass

            # 3. Process DPI Aware (Windows Vista+)
            try:
                if ctypes.windll.user32.SetProcessDPIAware():
                    return
            except Exception:
                pass
        except Exception:
            pass


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
        setup_windows_dpi_awareness()
        from videoremix.ui.app import main as gui_main
        gui_main()
    except Exception as exc:
        print(f"[VideoRemix] Notice: Native GUI could not start ({exc}).")
        print("[VideoRemix] Launching resilient Web UI interface instead...")
        from videoremix.ui.web import main as web_main
        web_main()


if __name__ == "__main__":
    main()
