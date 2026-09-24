"""FFmpeg subprocess execution and real-time progress parsing."""

import logging
import os
import re
import subprocess
import threading
import time
from typing import Callable, List, Optional
from videoremix.core.filtergraph import FilterGraphBuilder
from videoremix.core.hardware import EncoderConfig, HardwareDetector
from videoremix.core.probe import MediaInfo, get_ffmpeg_bin

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str, float], None]  # (percentage, speed, eta_sec)


class ExecutionCancelledError(Exception):
    pass


class FFmpegExecutor:
    """Manages FFmpeg transcode execution, real-time progress parsing, and cancellation."""

    def __init__(self, ffmpeg_bin: Optional[str] = None):
        self.ffmpeg_bin = ffmpeg_bin or get_ffmpeg_bin()
        self.process: Optional[subprocess.Popen] = None
        self._cancelled = False
        self._lock = threading.Lock()

    def cancel(self):
        """Cancel ongoing transcode process."""
        with self._lock:
            self._cancelled = True
            if self.process and self.process.poll() is None:
                try:
                    self.process.terminate()
                except Exception:
                    pass

    def run_remediation(
        self,
        media_info: MediaInfo,
        builder: FilterGraphBuilder,
        output_path: str,
        encoder_config: Optional[EncoderConfig] = None,
        on_progress: Optional[ProgressCallback] = None,
    ) -> str:
        """Execute the remediation filter pipeline and write output."""
        self._cancelled = False
        encoder = encoder_config or HardwareDetector.detect_best_encoder(self.ffmpeg_bin)

        # Build full command
        cmd: List[str] = [self.ffmpeg_bin, "-y", "-i", media_info.file_path]

        # Add filters and metadata
        cmd.extend(builder.build_ffmpeg_args())

        # Video encoding
        if media_info.has_video:
            cmd.extend(["-c:v", encoder.video_codec])
            cmd.extend(encoder.video_args)
        else:
            cmd.extend(["-vn"])

        # Audio encoding
        if media_info.has_audio:
            cmd.extend(["-c:a", encoder.audio_codec])
            cmd.extend(encoder.audio_args)
        else:
            cmd.extend(["-an"])

        # Ensure output directory exists
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        cmd.append(output_path)

        logger.info(f"Executing: {' '.join(cmd)}")

        # Calculate estimated target duration (considering speed adjustments)
        target_duration = media_info.duration / builder.speed_ratio if builder.speed_ratio > 0 else media_info.duration
        target_duration = max(0.1, target_duration)

        with self._lock:
            if self._cancelled:
                raise ExecutionCancelledError("Task was cancelled prior to start")
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )

        start_time = time.time()

        try:
            while True:
                line = self.process.stderr.readline()
                if not line and self.process.poll() is not None:
                    break

                if self._cancelled:
                    self.process.terminate()
                    raise ExecutionCancelledError("Execution cancelled by user")

                if on_progress and line:
                    self._parse_progress(line, target_duration, start_time, on_progress)

            rc = self.process.poll()
            if rc != 0 and not self._cancelled:
                raise RuntimeError(f"FFmpeg process exited with code {rc}")

            if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
                raise RuntimeError("Output file was not generated or is empty.")

            if on_progress:
                on_progress(100.0, "1.0x", 0.0)

            return output_path

        finally:
            with self._lock:
                self.process = None

    def _parse_progress(
        self,
        line: str,
        total_duration: float,
        start_time: float,
        callback: ProgressCallback,
    ):
        """Extract time, speed, and calculate ETA."""
        time_match = re.search(r"time=(\d+):(\d+):(\d+\.?\d*)", line)
        if time_match:
            h = int(time_match.group(1))
            m = int(time_match.group(2))
            s = float(time_match.group(3))
            current_time = h * 3600 + m * 60 + s

            percent = min(99.5, max(0.0, (current_time / total_duration) * 100.0))

            speed_match = re.search(r"speed=\s*([\d\.]+)x", line)
            speed_str = f"{speed_match.group(1)}x" if speed_match else "1.0x"

            elapsed = time.time() - start_time
            if percent > 0.5:
                eta = (elapsed / (percent / 100.0)) - elapsed
            else:
                eta = 0.0

            callback(round(percent, 1), speed_str, round(max(0.0, eta), 1))
