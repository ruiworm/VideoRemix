"""Automated release packaging script for VideoRemix."""

import os
import shutil
import subprocess
import sys
import imageio_ffmpeg


def build_release():
    is_win = sys.platform.startswith("win") or (os.name == "nt")
    ffmpeg_src = imageio_ffmpeg.get_ffmpeg_exe()
    print(f"[*] Detected source FFmpeg at: {ffmpeg_src}")

    # 1. Build portable onedir distribution
    print("\n=== [1/2] Building Portable Onedir Distribution ===")
    spec_path = os.path.join(os.path.dirname(__file__), "videoremix.spec")
    subprocess.run([sys.executable, "-m", "PyInstaller", "--clean", "-y", spec_path], check=True)

    dest_dir = os.path.join("dist", "VideoRemix")
    os.makedirs(dest_dir, exist_ok=True)

    # Bundle single FFmpeg binary into dist/VideoRemix
    target_name = "ffmpeg.exe" if is_win else "ffmpeg"
    target_ffmpeg = os.path.join(dest_dir, target_name)
    shutil.copy2(ffmpeg_src, target_ffmpeg)
    if not is_win:
        os.chmod(target_ffmpeg, 0o755)
    print(f"[*] Cleanly bundled FFmpeg to: {target_ffmpeg}")

    # Write portable README notice
    readme_path = os.path.join(dest_dir, "README_PORTABLE.txt")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write("VideoRemix Pro - Portable Standalone Edition\n")
        f.write("============================================\n\n")
        f.write("1. Double click VideoRemix.exe (Windows) or ./VideoRemix (Linux/macOS) to launch GUI.\n")
        f.write("2. Run 'VideoRemix --web' to launch browser-based Web UI.\n")
        f.write("3. Run 'VideoRemix input.mp4 -o output.mp4 --preset balanced' for CLI.\n\n")
        f.write("No Python or FFmpeg installation required. All dependencies are bundled.\n")

    # 2. On Windows: ALSO build Single-file Standalone .EXE (Zero extraction required)
    if is_win:
        print("\n=== [2/2] Building Single-file Standalone EXE (Zero Extraction) ===")
        onefile_cmd = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--clean",
            "-y",
            "--onefile",
            "--windowed",
            "--name",
            "VideoRemix-windows-x64",
            "--add-binary",
            f"{ffmpeg_src};.",
            "--hidden-import",
            "videoremix",
            "--hidden-import",
            "videoremix.launcher",
            "--hidden-import",
            "videoremix.ui.app",
            "--hidden-import",
            "videoremix.ui.web",
            "--hidden-import",
            "imageio_ffmpeg",
            "--hidden-import",
            "tkinter",
            "--paths",
            ".",
            "videoremix/launcher.py",
        ]
        subprocess.run(onefile_cmd, check=True)
        onefile_src = os.path.join("dist", "VideoRemix-windows-x64.exe")
        onefile_dst = "VideoRemix-windows-x64.exe"
        if os.path.exists(onefile_src):
            shutil.copy2(onefile_src, onefile_dst)
            print(f"[*] Successfully generated standalone EXE: {onefile_dst}")

    print("\n[OK] Build completed successfully!")


if __name__ == "__main__":
    build_release()
