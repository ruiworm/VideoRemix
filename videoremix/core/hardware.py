"""Hardware acceleration detection and encoder configuration."""

from dataclasses import dataclass, field
import platform
import subprocess
from typing import List, Optional
from videoremix.core.probe import get_ffmpeg_bin


@dataclass
class EncoderConfig:
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    video_args: List[str] = field(default_factory=lambda: ["-preset", "medium", "-crf", "21"])
    audio_args: List[str] = field(default_factory=lambda: ["-b:a", "192k"])
    is_hardware: bool = False
    name: str = "CPU (x264)"


class HardwareDetector:
    _cached_config: Optional[EncoderConfig] = None

    @classmethod
    def get_supported_encoders(cls, ffmpeg_bin: Optional[str] = None) -> List[str]:
        bin_path = ffmpeg_bin or get_ffmpeg_bin()
        try:
            res = subprocess.run([bin_path, "-encoders"], capture_output=True, text=True, check=True)
            encoders = []
            for line in res.stdout.splitlines():
                if "V....." in line or "V.S..." in line:
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        encoders.append(parts[1])
            return encoders
        except Exception:
            return ["libx264"]

    @classmethod
    def detect_best_encoder(cls, ffmpeg_bin: Optional[str] = None, force_cpu: bool = False) -> EncoderConfig:
        if cls._cached_config is not None and not force_cpu:
            return cls._cached_config

        if force_cpu:
            return EncoderConfig(
                video_codec="libx264",
                audio_codec="aac",
                video_args=["-preset", "medium", "-crf", "21"],
                audio_args=["-b:a", "192k"],
                is_hardware=False,
                name="CPU Software (libx264)"
            )

        supported = cls.get_supported_encoders(ffmpeg_bin)
        system = platform.system()

        # 1. NVIDIA NVENC
        if "h264_nvenc" in supported:
            # Test if NVENC actually initialises (driver present)
            if cls._test_encoder("h264_nvenc", ffmpeg_bin):
                cfg = EncoderConfig(
                    video_codec="h264_nvenc",
                    audio_codec="aac",
                    video_args=["-preset", "p4", "-cq", "22"],
                    audio_args=["-b:a", "192k"],
                    is_hardware=True,
                    name="NVIDIA NVENC (GPU)"
                )
                cls._cached_config = cfg
                return cfg

        # 2. Apple VideoToolbox (macOS)
        if system == "Darwin" and "h264_videotoolbox" in supported:
            if cls._test_encoder("h264_videotoolbox", ffmpeg_bin):
                cfg = EncoderConfig(
                    video_codec="h264_videotoolbox",
                    audio_codec="aac",
                    video_args=["-q:v", "65"],
                    audio_args=["-b:a", "192k"],
                    is_hardware=True,
                    name="Apple VideoToolbox (GPU)"
                )
                cls._cached_config = cfg
                return cfg

        # 3. Intel QuickSync (QSV)
        if "h264_qsv" in supported:
            if cls._test_encoder("h264_qsv", ffmpeg_bin):
                cfg = EncoderConfig(
                    video_codec="h264_qsv",
                    audio_codec="aac",
                    video_args=["-global_quality", "22"],
                    audio_args=["-b:a", "192k"],
                    is_hardware=True,
                    name="Intel QuickSync (QSV)"
                )
                cls._cached_config = cfg
                return cfg

        # 4. AMD AMF
        if "h264_amf" in supported:
            if cls._test_encoder("h264_amf", ffmpeg_bin):
                cfg = EncoderConfig(
                    video_codec="h264_amf",
                    audio_codec="aac",
                    video_args=["-quality", "balanced", "-rc", "cqp", "-qp_p", "22", "-qp_i", "22"],
                    audio_args=["-b:a", "192k"],
                    is_hardware=True,
                    name="AMD AMF (GPU)"
                )
                cls._cached_config = cfg
                return cfg

        # Fallback to libx264
        cfg = EncoderConfig(
            video_codec="libx264",
            audio_codec="aac",
            video_args=["-preset", "medium", "-crf", "21"],
            audio_args=["-b:a", "192k"],
            is_hardware=False,
            name="CPU Software (libx264)"
        )
        cls._cached_config = cfg
        return cfg

    @classmethod
    def _test_encoder(cls, encoder: str, ffmpeg_bin: Optional[str] = None) -> bool:
        bin_path = ffmpeg_bin or get_ffmpeg_bin()
        test_cmd = [
            bin_path, "-v", "quiet",
            "-f", "lavfi", "-i", "nullsrc=s=64x64:d=0.1",
            "-c:v", encoder,
            "-f", "null", "-"
        ]
        try:
            res = subprocess.run(test_cmd, capture_output=True, timeout=3)
            return res.returncode == 0
        except Exception:
            return False
