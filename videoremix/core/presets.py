"""Preset modes for video deduplication and remediation."""

from enum import Enum
from typing import Any, Dict
from videoremix.core.filtergraph import FilterGraphBuilder


class PresetMode(str, Enum):
    QUALITY_FIRST = "quality"        # Minimal visual loss, subtle acoustic & spatial perturbation
    BALANCED_REMIX = "balanced"      # High effectiveness: sync speed + zoom + audio pitch & EQ
    SMART_PIP = "pip"                # Picture-in-picture with blurred background
    CUSTOM = "custom"                # Custom settings


PRESET_DESCRIPTIONS: Dict[PresetMode, str] = {
    PresetMode.QUALITY_FIRST: "【画质保真】轻量色彩调优 + 微变调 + 底噪混入 + 胶片微噪点（零观感破坏）",
    PresetMode.BALANCED_REMIX: "【强效去重】微平移微缩放 + 同步变速 1.018x + 音高微调 + 均衡重构（音画严格对齐）",
    PresetMode.SMART_PIP: "【智能画中画】90% 居中原画 + 动态高斯模糊背景 + 全面声学指纹重塑（强力变体）",
    PresetMode.CUSTOM: "【自定义模式】自由勾选微调参数与强度",
}


def apply_preset(
    builder: FilterGraphBuilder,
    preset: PresetMode = PresetMode.BALANCED_REMIX,
    **custom_opts: Any
) -> FilterGraphBuilder:
    """Configure a FilterGraphBuilder using predefined preset parameters."""
    builder.set_clean_metadata(randomize_tags=True)

    if preset == PresetMode.QUALITY_FIRST:
        builder.add_color_grade(contrast=1.02, brightness=0.008, saturation=1.03, gamma=1.01)
        builder.add_film_grain(intensity=2)
        builder.add_pitch_shift(semitones=0.20)
        builder.add_noise_floor()

    elif preset == PresetMode.BALANCED_REMIX:
        builder.add_subtle_crop_zoom(zoom=1.02)
        builder.add_color_grade(contrast=1.02, brightness=0.01, saturation=1.03)
        builder.add_film_grain(intensity=3)
        builder.set_sync_speed(speed_ratio=1.018)
        builder.add_pitch_shift(semitones=0.25)
        builder.add_equalizer(low_gain_db=0.8, high_gain_db=-0.8)
        builder.add_noise_floor()

    elif preset == PresetMode.SMART_PIP:
        builder.add_smart_pip(scale=0.90, blur=18)
        builder.add_color_grade(contrast=1.02, saturation=1.03)
        builder.add_film_grain(intensity=2)
        builder.set_sync_speed(speed_ratio=1.015)
        builder.add_pitch_shift(semitones=0.30)
        builder.add_equalizer(low_gain_db=1.0, high_gain_db=-1.0)
        builder.add_noise_floor()

    elif preset == PresetMode.CUSTOM:
        if custom_opts.get("zoom", 1.0) > 1.0:
            builder.add_subtle_crop_zoom(custom_opts["zoom"])
        if custom_opts.get("grain", 0) > 0:
            builder.add_film_grain(custom_opts["grain"])
        if custom_opts.get("color_grade", False):
            builder.add_color_grade()
        if custom_opts.get("hflip", False):
            builder.add_mirror_hflip()
        if custom_opts.get("pip", False):
            builder.add_smart_pip()
        if custom_opts.get("speed", 1.0) != 1.0:
            builder.set_sync_speed(custom_opts["speed"])
        if custom_opts.get("pitch_semitones", 0.0) != 0.0:
            builder.add_pitch_shift(custom_opts["pitch_semitones"])
        if custom_opts.get("equalizer", False):
            builder.add_equalizer()
        if custom_opts.get("noise_floor", False):
            builder.add_noise_floor()

    return builder
