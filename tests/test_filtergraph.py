from videoremix.core.filtergraph import FilterGraphBuilder
from videoremix.core.presets import PresetMode, apply_preset
from videoremix.core.probe import MediaInfo

def test_filtergraph_builder_basic():
    info = MediaInfo(file_path="dummy.mp4", duration=10.0, has_video=True, has_audio=True, sample_rate=44100)
    builder = FilterGraphBuilder(info)
    builder.add_subtle_crop_zoom(1.02)
    builder.add_film_grain(3)
    builder.add_pitch_shift(0.25)
    builder.set_sync_speed(1.018)
    builder.set_clean_metadata(True)

    args = builder.build_ffmpeg_args()
    assert "-map_metadata" in args
    assert "-vf" in args
    assert "-af" in args

    vf_idx = args.index("-vf")
    vf_str = args[vf_idx + 1]
    assert "scale=" in vf_str
    assert "crop=" in vf_str
    assert "noise=" in vf_str
    assert "setpts=" in vf_str

    af_idx = args.index("-af")
    af_str = args[af_idx + 1]
    assert "asetrate=" in af_str
    assert "atempo=" in af_str

def test_preset_application():
    info = MediaInfo(file_path="dummy.mp4", duration=10.0, has_video=True, has_audio=True)
    builder = FilterGraphBuilder(info)
    apply_preset(builder, PresetMode.BALANCED_REMIX)

    args = builder.build_ffmpeg_args()
    assert "-vf" in args
    assert "-af" in args
    assert "-map_metadata" in args

def test_smart_pip_filter():
    info = MediaInfo(file_path="dummy.mp4", duration=10.0, has_video=True, has_audio=True)
    builder = FilterGraphBuilder(info)
    apply_preset(builder, PresetMode.SMART_PIP)

    args = builder.build_ffmpeg_args()
    assert "-filter_complex" in args
    fc_idx = args.index("-filter_complex")
    fc_str = args[fc_idx + 1]
    assert "boxblur=" in fc_str
    assert "overlay=" in fc_str
