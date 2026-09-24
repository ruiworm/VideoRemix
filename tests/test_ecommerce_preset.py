"""Unit tests for the E-Commerce anti-interception preset (ECOMMERCE)."""

import json
from io import BytesIO
import os
import tempfile
from unittest.mock import MagicMock
import pytest

from videoremix.core.filtergraph import FilterGraphBuilder
from videoremix.core.presets import PresetMode, apply_preset
from videoremix.core.probe import MediaInfo
from videoremix.queue.manager import BatchQueueManager
from videoremix.queue.task import RemediationTask, TaskStatus
from videoremix.ui.web import WebUIServer


def _make_dummy_media_info() -> MediaInfo:
    return MediaInfo(
        file_path="dummy.mp4",
        duration=10.0,
        width=1920,
        height=1080,
        fps=30.0,
        vcodec="h264",
        acodec="aac",
        sample_rate=44100,
        channels=2,
        bitrate_kbps=2500,
        has_video=True,
        has_audio=True,
    )


def test_ecommerce_preset_filters_generated():
    info = _make_dummy_media_info()
    builder = FilterGraphBuilder(info)

    apply_preset(builder, PresetMode.ECOMMERCE)
    args = builder.build_ffmpeg_args()

    assert "-vf" in args
    vf_str = args[args.index("-vf") + 1]
    # Check bottom subtitle mask
    assert "drawbox=" in vf_str
    assert "color=black@0.70" in vf_str
    # Check crop and zoom
    assert "scale=" in vf_str
    assert "crop=" in vf_str
    # Check color grade and film grain
    assert "eq=" in vf_str
    assert "noise=" in vf_str
    # Check video speedup
    assert "setpts=PTS/1.0280" in vf_str

    assert "-af" in args
    af_str = args[args.index("-af") + 1]
    # Check acoustic pitch shift and equalizer
    assert "asetrate=" in af_str
    assert "equalizer=" in af_str
    assert "aeval=" in af_str
    # Check audio speedup
    assert "atempo=1.0280" in af_str


def test_ecommerce_preset_with_hflip_option():
    info = _make_dummy_media_info()
    builder = FilterGraphBuilder(info)

    apply_preset(builder, PresetMode.ECOMMERCE, hflip=True)
    args = builder.build_ffmpeg_args()

    vf_str = args[args.index("-vf") + 1]
    assert "hflip" in vf_str
    assert "drawbox=" in vf_str


def test_custom_mode_supports_subtitle_mask():
    info = _make_dummy_media_info()
    builder = FilterGraphBuilder(info)

    apply_preset(builder, PresetMode.CUSTOM, subtitle_mask=True, zoom=1.0)
    args = builder.build_ffmpeg_args()

    assert "-vf" in args
    vf_str = args[args.index("-vf") + 1]
    assert "drawbox=" in vf_str


def test_web_api_ecommerce_preset_handling():
    server = WebUIServer(port=9998)
    handler_class = server.create_handler()

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        dummy_video = f.name

    try:
        req_body = json.dumps({
            "input": dummy_video,
            "output": "",
            "preset": "ecommerce",
            "workers": 2,
        }).encode("utf-8")

        handler = handler_class.__new__(handler_class)
        handler.rfile = BytesIO(req_body)
        handler.wfile = BytesIO()
        handler.headers = {"Content-Length": str(len(req_body))}
        handler.path = "/api/tasks/add"
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        handler.do_POST()

        assert len(server.queue_manager.tasks) == 1
        task = server.queue_manager.tasks[0]
        assert task.preset == PresetMode.ECOMMERCE

        # Check /api/status formatting
        handler.path = "/api/status"
        handler.wfile = BytesIO()
        handler.do_GET()

        data = json.loads(handler.wfile.getvalue().decode("utf-8"))
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["preset"] == "电商专版"

    finally:
        if os.path.exists(dummy_video):
            os.remove(dummy_video)
