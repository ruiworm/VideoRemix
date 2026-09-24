import pytest
from videoremix.core.probe import probe_media, MediaInfo

def test_probe_media_sample():
    info = probe_media("/home/vere/VideoRemix/sample.mp4")
    assert isinstance(info, MediaInfo)
    assert info.has_video is True
    assert info.has_audio is True
    assert info.width == 1280
    assert info.height == 720
    assert info.duration >= 2.9
    assert info.sample_rate == 44100
