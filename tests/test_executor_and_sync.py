import hashlib
import os
from videoremix.core.executor import FFmpegExecutor
from videoremix.core.filtergraph import FilterGraphBuilder
from videoremix.core.presets import PresetMode, apply_preset
from videoremix.core.probe import probe_media

def test_transcode_and_sync(sample_video, tmp_path):
    input_file = sample_video
    output_file = str(tmp_path / "test_sync_out.mp4")

    info = probe_media(input_file)
    builder = FilterGraphBuilder(info)
    apply_preset(builder, PresetMode.BALANCED_REMIX)

    progress_records = []
    def on_p(pct, spd, eta):
        progress_records.append(pct)

    executor = FFmpegExecutor()
    res = executor.run_remediation(info, builder, output_file, on_progress=on_p)
    assert os.path.exists(res)
    assert os.path.getsize(res) > 0

    out_info = probe_media(output_file)
    assert out_info.has_video is True
    assert out_info.has_audio is True

    # Check that audio and video remain strictly synchronized
    expected_duration = 3.0 / 1.018  # balanced remix applies 1.018x speed
    assert abs(out_info.duration - expected_duration) < 0.1

    # Verify MD5 perturbation
    with open(input_file, "rb") as f:
        in_md5 = hashlib.md5(f.read()).hexdigest()
    with open(output_file, "rb") as f:
        out_md5 = hashlib.md5(f.read()).hexdigest()

    assert in_md5 != out_md5
    assert len(progress_records) > 0
