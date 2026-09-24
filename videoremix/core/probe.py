"""Media probing and metadata extraction module."""

from dataclasses import dataclass
import json
import os
import re
import shutil
import subprocess
import sys
from typing import Optional


def get_ffmpeg_bin() -> str:
    """Find FFmpeg binary from PyInstaller bundle, imageio_ffmpeg, system PATH, or local directory."""
    # 1. PyInstaller frozen binary bundle
    if getattr(sys, "frozen", False):
        candidates = []
        if hasattr(sys, "_MEIPASS"):
            meipass = sys._MEIPASS
            candidates.extend([
                os.path.join(meipass, "ffmpeg.exe"),
                os.path.join(meipass, "ffmpeg"),
                os.path.join(meipass, "bin", "ffmpeg.exe"),
                os.path.join(meipass, "bin", "ffmpeg"),
            ])
            # Dynamically scan sys._MEIPASS for any file starting with ffmpeg (such as ffmpeg-win64-*.exe)
            if os.path.isdir(meipass):
                try:
                    for root_dir, _, filenames in os.walk(meipass):
                        for fn in filenames:
                            fn_lower = fn.lower()
                            if fn_lower.startswith("ffmpeg") and not fn_lower.endswith(
                                (".py", ".pyc", ".pyo", ".pyd", ".txt", ".json", ".md", ".rst", ".html", ".dll")
                            ):
                                cand_path = os.path.join(root_dir, fn)
                                if os.path.isfile(cand_path):
                                    candidates.append(cand_path)
                except Exception:
                    pass

        exe_dir = os.path.dirname(sys.executable)
        candidates.extend([
            os.path.join(exe_dir, "ffmpeg.exe"),
            os.path.join(exe_dir, "ffmpeg"),
            os.path.join(exe_dir, "bin", "ffmpeg.exe"),
            os.path.join(exe_dir, "bin", "ffmpeg"),
        ])
        for cand in candidates:
            if os.path.isfile(cand) and os.path.exists(cand):
                if (sys.platform.startswith("win") or os.name == "nt") and not cand.lower().endswith(".exe"):
                    continue
                return os.path.abspath(cand)

    # 2. imageio-ffmpeg
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass

    # 3. System PATH
    system_bin = shutil.which("ffmpeg")
    if system_bin:
        return system_bin

    # 4. Local fallback
    for candidate in ["./ffmpeg", "./bin/ffmpeg", "./ffmpeg.exe", "./bin/ffmpeg.exe"]:
        if os.path.exists(candidate):
            return os.path.abspath(candidate)

    raise FileNotFoundError("FFmpeg executable not found. Please install FFmpeg or imageio-ffmpeg.")


def get_ffprobe_bin() -> Optional[str]:
    """Find FFprobe binary if available."""
    if getattr(sys, "frozen", False):
        candidates = []
        if hasattr(sys, "_MEIPASS"):
            candidates.extend([
                os.path.join(sys._MEIPASS, "ffprobe.exe"),
                os.path.join(sys._MEIPASS, "ffprobe"),
            ])
        exe_dir = os.path.dirname(sys.executable)
        candidates.extend([
            os.path.join(exe_dir, "ffprobe.exe"),
            os.path.join(exe_dir, "ffprobe"),
        ])
        for cand in candidates:
            if os.path.exists(cand):
                return os.path.abspath(cand)

    system_bin = shutil.which("ffprobe")
    if system_bin:
        return system_bin

    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin:
        probe_cand = os.path.join(os.path.dirname(ffmpeg_bin), "ffprobe")
        if os.path.exists(probe_cand):
            return probe_cand
        probe_cand_exe = probe_cand + ".exe"
        if os.path.exists(probe_cand_exe):
            return probe_cand_exe

    return None


@dataclass
class MediaInfo:
    """Holds detailed video and audio stream metadata."""
    file_path: str
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 30.0
    vcodec: Optional[str] = None
    acodec: Optional[str] = None
    sample_rate: int = 44100
    channels: int = 2
    bitrate_kbps: int = 0
    has_video: bool = False
    has_audio: bool = False

    @property
    def aspect_ratio(self) -> float:
        return (self.width / self.height) if self.height > 0 else 16 / 9


def probe_media(file_path: str, ffmpeg_bin: Optional[str] = None, ffprobe_bin: Optional[str] = None) -> MediaInfo:
    """Probe a media file using ffprobe (if available) or falling back to ffmpeg banner output."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Media file not found: {file_path}")

    ffprobe = ffprobe_bin or get_ffprobe_bin()
    if ffprobe and os.path.exists(ffprobe):
        try:
            return _probe_with_ffprobe(file_path, ffprobe)
        except Exception:
            pass  # Fall back to ffmpeg banner parse

    ffmpeg = ffmpeg_bin or get_ffmpeg_bin()
    return _probe_with_ffmpeg(file_path, ffmpeg)


def _probe_with_ffprobe(file_path: str, ffprobe_bin: str) -> MediaInfo:
    extra_kwargs = {}
    if sys.platform.startswith("win") or (os.name == "nt"):
        extra_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    cmd = [
        ffprobe_bin,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        file_path,
    ]
    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
        stdin=subprocess.DEVNULL,
        encoding="utf-8",
        errors="replace",
        **extra_kwargs,
    )
    data = json.loads(res.stdout)

    info = MediaInfo(file_path=file_path)
    fmt = data.get("format", {})
    info.duration = float(fmt.get("duration", 0.0))
    info.bitrate_kbps = int(float(fmt.get("bit_rate", 0)) / 1000) if fmt.get("bit_rate") else 0

    for stream in data.get("streams", []):
        codec_type = stream.get("codec_type")
        if codec_type == "video" and not info.has_video:
            info.has_video = True
            info.vcodec = stream.get("codec_name")
            info.width = int(stream.get("width", 0))
            info.height = int(stream.get("height", 0))

            # FPS parsing (e.g. "30/1" or "29.97")
            r_frame_rate = stream.get("r_frame_rate", "30/1")
            try:
                num, den = map(float, r_frame_rate.split("/"))
                info.fps = round(num / den, 3) if den != 0 else 30.0
            except Exception:
                info.fps = 30.0

        elif codec_type == "audio" and not info.has_audio:
            info.has_audio = True
            info.acodec = stream.get("codec_name")
            info.sample_rate = int(stream.get("sample_rate", 44100))
            info.channels = int(stream.get("channels", 2))

    if not info.has_video and not info.has_audio:
        raise RuntimeError(f"No video or audio stream found in {file_path}")

    return info


def _probe_with_ffmpeg(file_path: str, ffmpeg_bin: str) -> MediaInfo:
    extra_kwargs = {}
    if sys.platform.startswith("win") or (os.name == "nt"):
        extra_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    cmd = [ffmpeg_bin, "-hide_banner", "-i", file_path]
    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        encoding="utf-8",
        errors="replace",
        **extra_kwargs,
    )
    text = res.stderr or ""

    info = MediaInfo(file_path=file_path)

    # 1. Parse Duration
    dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", text)
    if dur_match:
        h = int(dur_match.group(1))
        m = int(dur_match.group(2))
        s = float(dur_match.group(3))
        info.duration = round(h * 3600 + m * 60 + s, 3)

    # 2. Parse Bitrate
    bitrate_match = re.search(r"bitrate:\s*(\d+)\s*kb/s", text)
    if bitrate_match:
        info.bitrate_kbps = int(bitrate_match.group(1))

    # 3. Parse Video Stream
    # Format e.g.: Stream #0:0(und): Video: h264 (High) (avc1 / ...), yuv420p(tv, ...), 1280x720 [SAR 1:1 DAR 16:9], 30 fps
    video_match = re.search(
        r"Stream #\d+:\d+.*?: Video:\s*([a-zA-Z0-9_-]+).*?,\s*(\d+)x(\d+).*?,\s*([\d\.]+)\s*(?:fps|tbr)",
        text,
    )
    if video_match:
        info.has_video = True
        info.vcodec = video_match.group(1).strip()
        info.width = int(video_match.group(2))
        info.height = int(video_match.group(3))
        info.fps = float(video_match.group(4))
    else:
        # Fallback simpler video check
        v_simple = re.search(r"Stream #\d+:\d+.*?: Video:\s*([a-zA-Z0-9_-]+).*?,\s*(\d+)x(\d+)", text)
        if v_simple:
            info.has_video = True
            info.vcodec = v_simple.group(1).strip()
            info.width = int(v_simple.group(2))
            info.height = int(v_simple.group(3))

    # 4. Parse Audio Stream
    # Format e.g.: Stream #0:1(und): Audio: aac (LC) (mp4a / ...), 44100 Hz, stereo, fltp, 128 kb/s
    audio_match = re.search(
        r"Stream #\d+:\d+.*?: Audio:\s*([a-zA-Z0-9_-]+).*?,\s*(\d+)\s*Hz,\s*([^,]+)",
        text,
    )
    if audio_match:
        info.has_audio = True
        info.acodec = audio_match.group(1).strip()
        info.sample_rate = int(audio_match.group(2))
        ch_str = audio_match.group(3).lower()
        if "stereo" in ch_str:
            info.channels = 2
        elif "mono" in ch_str:
            info.channels = 1
        elif "5.1" in ch_str:
            info.channels = 6
        else:
            info.channels = 2

    if not info.has_video and not info.has_audio:
        stderr_tail = "\n".join(text.strip().splitlines()[-15:]) if text.strip() else "(no stderr output)"
        raise RuntimeError(
            f"Failed to probe media file '{file_path}': No video or audio streams detected.\n"
            f"FFmpeg stderr tail:\n{stderr_tail}"
        )

    return info
