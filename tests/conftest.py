"""Pytest test fixtures for VideoRemix tests."""

import subprocess
import pytest
from videoremix.core.probe import get_ffmpeg_bin


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory):
    """Generates a synthetic 3-second 720p MP4 file with video and audio tracks."""
    out_dir = tmp_path_factory.mktemp("test_media")
    video_path = out_dir / "sample.mp4"
    ffmpeg = get_ffmpeg_bin()
    cmd = [
        ffmpeg, "-y",
        "-f", "lavfi", "-i", "testsrc=duration=3:size=1280x720:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=3",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "44100",
        str(video_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Failed to generate test sample video: {res.stderr}")
    return str(video_path)
