import json
import os
from pathlib import Path
import threading
import time
import urllib.request
import pytest

from videoremix.core.filtergraph import FilterGraphBuilder
from videoremix.core.presets import PresetMode, apply_preset
from videoremix.core.probe import MediaInfo
from videoremix.queue.manager import BatchQueueManager
from videoremix.ui.web import WebUIServer


def test_filtergraph_add_trim():
    # 1. Trim with known duration
    info = MediaInfo(file_path="sample.mp4", duration=10.0, width=1920, height=1080, has_video=True, has_audio=True)
    builder = FilterGraphBuilder(info)
    builder.add_subtle_crop_zoom(1.02)
    builder.add_trim(trim_start=1.0, trim_end=0.5)

    args = builder.build_ffmpeg_args()
    v_filter = args[args.index("-vf") + 1]
    a_filter = args[args.index("-af") + 1]

    # trim must be at index 0
    assert "trim=start=1.000:end=9.500,setpts=PTS-STARTPTS" in v_filter
    assert v_filter.startswith("trim=start=1.000:end=9.500,setpts=PTS-STARTPTS")
    assert "atrim=start=1.000:end=9.500,asetpts=PTS-STARTPTS" in a_filter
    assert a_filter.startswith("atrim=start=1.000:end=9.500,asetpts=PTS-STARTPTS")

    # 2. Trim without end or unknown duration
    info2 = MediaInfo(file_path="sample.mp4", duration=0.0, width=1920, height=1080, has_video=True, has_audio=True)
    builder2 = FilterGraphBuilder(info2)
    builder2.add_trim(trim_start=0.8, trim_end=0.0)
    args2 = builder2.build_ffmpeg_args()
    v_filter2 = args2[args2.index("-vf") + 1]
    a_filter2 = args2[args2.index("-af") + 1]
    assert "trim=start=0.800,setpts=PTS-STARTPTS" in v_filter2
    assert "atrim=start=0.800,asetpts=PTS-STARTPTS" in a_filter2


def test_presets_random_jitter_and_trim():
    # E-commerce preset with randomize=True
    filter_outputs = []
    for _ in range(5):
        info = MediaInfo(file_path="demo.mp4", duration=20.0, width=1920, height=1080, has_video=True, has_audio=True)
        b = FilterGraphBuilder(info)
        apply_preset(b, PresetMode.ECOMMERCE, randomize=True)
        args = b.build_ffmpeg_args()
        v_f = args[args.index("-vf") + 1]
        filter_outputs.append(v_f)

    # At least two of the random outputs should differ due to jitter
    assert len(set(filter_outputs)) > 1

    # Custom preset with trim
    info_c = MediaInfo(file_path="demo.mp4", duration=15.0, width=1920, height=1080, has_video=True, has_audio=True)
    builder_custom = FilterGraphBuilder(info_c)
    apply_preset(
        builder_custom,
        PresetMode.CUSTOM,
        trim_start=1.2,
        trim_end=0.6,
        zoom=1.04,
        speed=1.025,
        randomize=False,
    )
    args_c = builder_custom.build_ffmpeg_args()
    v_f = args_c[args_c.index("-vf") + 1]
    assert "trim=start=1.200:end=14.400,setpts=PTS-STARTPTS" in v_f
    assert "crop=" in v_f
    assert "setpts=PTS/1.0250" in v_f


def test_queue_variant_multiplier(tmp_path):
    video = tmp_path / "product_demo.mp4"
    video.write_bytes(b"dummy video content")

    manager = BatchQueueManager()
    tasks = manager.add_task(str(video), variants=3, preset=PresetMode.ECOMMERCE)

    assert isinstance(tasks, list)
    assert len(tasks) == 3
    assert tasks[0].filename == "product_demo.mp4 [v1]"
    assert tasks[1].filename == "product_demo.mp4 [v2]"
    assert tasks[2].filename == "product_demo.mp4 [v3]"
    assert tasks[0].output_filename == "product_demo_v1_remix.mp4"
    assert tasks[1].output_filename == "product_demo_v2_remix.mp4"
    assert tasks[2].output_filename == "product_demo_v3_remix.mp4"
    assert tasks[0].custom_opts.get("randomize") is True
    assert tasks[1].custom_opts.get("randomize") is True
    assert tasks[2].custom_opts.get("randomize") is True


def test_queue_add_directory_variants(tmp_path):
    (tmp_path / "vid1.mp4").write_bytes(b"vid1")
    (tmp_path / "vid2.mp4").write_bytes(b"vid2")

    manager = BatchQueueManager()
    tasks = manager.add_directory(str(tmp_path), variants=2, preset=PresetMode.BALANCED_REMIX)

    # 2 files * 2 variants = 4 tasks
    assert len(tasks) == 4
    output_filenames = {t.output_filename for t in tasks}
    assert "vid1_v1_remix.mp4" in output_filenames
    assert "vid1_v2_remix.mp4" in output_filenames
    assert "vid2_v1_remix.mp4" in output_filenames
    assert "vid2_v2_remix.mp4" in output_filenames


def test_web_api_variants_and_open_folder(tmp_path):
    server = WebUIServer(port=8772)
    t = threading.Thread(target=server.start, kwargs={"open_browser": False}, daemon=True)
    t.start()
    time.sleep(0.3)

    sample_vid = tmp_path / "item.mp4"
    sample_vid.write_bytes(b"sample")

    # Add task with 2 variants
    payload = json.dumps({
        "input": str(sample_vid),
        "preset": "ecommerce",
        "variants": 2,
        "randomize": True,
    }).encode("utf-8")

    req = urllib.request.Request(
        "http://127.0.0.1:8772/api/tasks/add",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        assert res.get("success") is True
        assert res.get("added") == 2

    # Verify status reports 2 tasks
    with urllib.request.urlopen("http://127.0.0.1:8772/api/status") as resp:
        st = json.loads(resp.read().decode("utf-8"))
        assert len(st["tasks"]) == 2

    # Test open_folder endpoint
    open_payload = json.dumps({"folder": str(tmp_path)}).encode("utf-8")
    req_open = urllib.request.Request(
        "http://127.0.0.1:8772/api/open_folder",
        data=open_payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req_open) as resp:
        open_res = json.loads(resp.read().decode("utf-8"))
        assert open_res.get("success") is True
