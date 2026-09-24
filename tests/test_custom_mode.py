"""Tests for Custom deduplication mode across core, queue, web, and GUI layers."""

import os
import tempfile
from pathlib import Path
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


def test_custom_preset_filtergraph_all_options():
    info = _make_dummy_media_info()
    builder = FilterGraphBuilder(info)

    opts = {
        "zoom": 1.05,
        "speed": 1.03,
        "grain": 4,
        "pitch": 0.5,
        "hflip": True,
        "pip": False,
        "color_grade": True,
        "equalizer": True,
        "noise_floor": True,
    }

    apply_preset(builder, PresetMode.CUSTOM, **opts)

    args = builder.build_ffmpeg_args()
    combined_args = " ".join(args)

    # Verify video filters
    assert "-vf" in args
    vf_str = args[args.index("-vf") + 1]
    assert "crop=" in vf_str
    assert "noise=" in vf_str
    assert "hflip" in vf_str
    assert "eq=" in vf_str
    assert "setpts=PTS/" in vf_str

    # Verify audio filters
    assert "-af" in args
    af_str = args[args.index("-af") + 1]
    assert "asetrate=" in af_str
    assert "equalizer=" in af_str
    assert "aeval=" in af_str
    assert "atempo=" in af_str


def test_custom_preset_accepts_pitch_semitones_alias():
    info = _make_dummy_media_info()
    builder = FilterGraphBuilder(info)

    opts = {
        "pitch_semitones": 0.8,
    }

    apply_preset(builder, PresetMode.CUSTOM, **opts)
    args = builder.build_ffmpeg_args()
    assert "-af" in args
    af_str = args[args.index("-af") + 1]
    assert "asetrate=" in af_str


def test_custom_preset_minimal_options_skips_filters():
    info = _make_dummy_media_info()
    builder = FilterGraphBuilder(info)

    opts = {
        "zoom": 1.0,
        "speed": 1.0,
        "grain": 0,
        "pitch": 0.0,
        "hflip": False,
        "pip": False,
        "color_grade": False,
        "equalizer": False,
        "noise_floor": False,
    }

    apply_preset(builder, PresetMode.CUSTOM, **opts)
    args = builder.build_ffmpeg_args()

    assert "-vf" not in args
    assert "-af" not in args
    assert "-filter_complex" not in args


def test_queue_manager_propagates_custom_opts():
    qm = BatchQueueManager(max_workers=1)

    custom_opts = {
        "zoom": 1.08,
        "speed": 1.025,
        "grain": 5,
        "hflip": True,
    }

    task = qm.add_task(
        "test_video.mp4",
        output_path="test_video_out.mp4",
        preset=PresetMode.CUSTOM,
        **custom_opts,
    )

    assert task.preset == PresetMode.CUSTOM
    assert task.custom_opts["zoom"] == 1.08
    assert task.custom_opts["speed"] == 1.025
    assert task.custom_opts["grain"] == 5
    assert task.custom_opts["hflip"] is True


def test_web_api_custom_task_handling():
    import json
    from io import BytesIO
    from unittest.mock import MagicMock

    server = WebUIServer(port=9999)
    handler_class = server.create_handler()

    # Create dummy video file
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        dummy_video = f.name

    try:
        req_body = json.dumps({
            "input": dummy_video,
            "output": "",
            "preset": "custom",
            "workers": 2,
            "custom_opts": {
                "zoom": 1.04,
                "speed": 1.015,
                "grain": 2,
                "pitch": 0.2,
                "hflip": False,
                "pip": False,
                "color_grade": True,
                "equalizer": True,
                "noise_floor": True,
            }
        }).encode("utf-8")

        mock_request = MagicMock()
        mock_request.makefile.return_value = BytesIO(req_body)

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
        enqueued_task = server.queue_manager.tasks[0]
        assert enqueued_task.preset == PresetMode.CUSTOM
        assert enqueued_task.custom_opts["zoom"] == 1.04
        assert enqueued_task.custom_opts["speed"] == 1.015

        # Check /api/status endpoint response
        handler.path = "/api/status"
        handler.wfile = BytesIO()
        handler.do_GET()

        response_data = json.loads(handler.wfile.getvalue().decode("utf-8"))
        assert len(response_data["tasks"]) == 1
        task_info = response_data["tasks"][0]
        assert "自定义 (1.04x/1.015x)" in task_info["preset"]
        assert task_info["custom_opts"]["zoom"] == 1.04

    finally:
        if os.path.exists(dummy_video):
            os.remove(dummy_video)
