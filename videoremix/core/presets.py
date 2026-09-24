"""Preset modes for video deduplication and remediation."""

from enum import Enum
import random
from typing import Any, Dict
from videoremix.core.filtergraph import FilterGraphBuilder


def _jitter(base_val: float, min_mult: float = 0.995, max_mult: float = 1.01) -> float:
    """Apply microscopic random perturbation to prevent batch fingerprint collisions."""
    return base_val * random.uniform(min_mult, max_mult)


class PresetMode(str, Enum):
    QUALITY_FIRST = "quality"        # Minimal visual loss, subtle acoustic & spatial perturbation
    BALANCED_REMIX = "balanced"      # High effectiveness: sync speed + zoom + audio pitch & EQ
    SMART_PIP = "pip"                # Picture-in-picture with blurred background
    ECOMMERCE = "ecommerce"          # E-commerce platform (JD/PDD) anti-interception preset
    CUSTOM = "custom"                # Custom settings


PRESET_DESCRIPTIONS: Dict[PresetMode, str] = {
    PresetMode.QUALITY_FIRST: "【画质保真】轻量色彩调优 + 微变调 + 底噪混入 + 胶片微噪点（零观感破坏）",
    PresetMode.BALANCED_REMIX: "【强效去重】微平移微缩放 + 同步变速 1.018x + 音高微调 + 均衡重构（音画严格对齐）",
    PresetMode.SMART_PIP: "【智能画中画】90% 居中原画 + 动态高斯模糊背景 + 全面声学指纹重塑（强力变体）",
    PresetMode.ECOMMERCE: "【电商专版】专克京东/拼多多初审 (底部字幕遮罩阻断OCR + 口播抗ASR变速微变调 + 4.5%边缘净空)",
    PresetMode.CUSTOM: "【自定义模式】自由勾选微调参数与强度",
}


def apply_preset(
    builder: FilterGraphBuilder,
    preset: PresetMode = PresetMode.BALANCED_REMIX,
    **custom_opts: Any
) -> FilterGraphBuilder:
    """Configure a FilterGraphBuilder using predefined preset parameters."""
    builder.set_clean_metadata(randomize_tags=True)

    randomize = bool(custom_opts.get("randomize", False))
    trim_start = float(custom_opts.get("trim_start", 0.0))
    trim_end = float(custom_opts.get("trim_end", 0.0))

    if preset == PresetMode.QUALITY_FIRST:
        contrast = _jitter(1.02, 0.995, 1.01) if randomize else 1.02
        saturation = _jitter(1.03, 0.995, 1.01) if randomize else 1.03
        pitch = 0.20 + (random.uniform(-0.03, 0.03) if randomize else 0.0)
        builder.add_color_grade(contrast=contrast, brightness=0.008, saturation=saturation, gamma=1.01)
        builder.add_film_grain(intensity=2)
        builder.add_pitch_shift(semitones=pitch)
        builder.add_noise_floor()

    elif preset == PresetMode.BALANCED_REMIX:
        zoom = _jitter(1.02, 0.995, 1.01) if randomize else 1.02
        speed = _jitter(1.018, 0.995, 1.008) if randomize else 1.018
        pitch = 0.25 + (random.uniform(-0.03, 0.03) if randomize else 0.0)
        builder.add_subtle_crop_zoom(zoom=zoom)
        builder.add_color_grade(contrast=1.02, brightness=0.01, saturation=1.03)
        builder.add_film_grain(intensity=3)
        builder.set_sync_speed(speed_ratio=speed)
        builder.add_pitch_shift(semitones=pitch)
        builder.add_equalizer(low_gain_db=0.8, high_gain_db=-0.8)
        builder.add_noise_floor()

    elif preset == PresetMode.SMART_PIP:
        speed = _jitter(1.015, 0.995, 1.008) if randomize else 1.015
        pitch = 0.30 + (random.uniform(-0.03, 0.03) if randomize else 0.0)
        builder.add_smart_pip(scale=0.90, blur=18)
        builder.add_color_grade(contrast=1.02, saturation=1.03)
        builder.add_film_grain(intensity=2)
        builder.set_sync_speed(speed_ratio=speed)
        builder.add_pitch_shift(semitones=pitch)
        builder.add_equalizer(low_gain_db=1.0, high_gain_db=-1.0)
        builder.add_noise_floor()

    elif preset == PresetMode.ECOMMERCE:
        # Default trim for e-commerce if not explicitly specified
        if "trim_start" not in custom_opts:
            trim_start = 0.8
        if "trim_end" not in custom_opts:
            trim_end = 0.5
        if randomize:
            trim_start = max(0.0, trim_start + random.uniform(-0.15, 0.15))
            trim_end = max(0.0, trim_end + random.uniform(-0.1, 0.1))

        zoom = _jitter(1.045, 0.995, 1.01) if randomize else 1.045
        speed = _jitter(1.028, 0.995, 1.008) if randomize else 1.028
        pitch = 0.35 + (random.uniform(-0.03, 0.03) if randomize else 0.0)

        builder.add_subtle_crop_zoom(zoom=zoom)
        builder.add_subtitle_mask(height_ratio=0.12, opacity=0.70)
        builder.add_color_grade(contrast=1.03, brightness=0.012, saturation=1.04, gamma=1.015)
        builder.add_film_grain(intensity=3)
        builder.set_sync_speed(speed_ratio=speed)
        builder.add_pitch_shift(semitones=pitch)
        builder.add_equalizer(low_gain_db=1.0, high_gain_db=-1.0)
        builder.add_noise_floor()
        if custom_opts.get("hflip", False):
            builder.add_mirror_hflip()

    elif preset == PresetMode.CUSTOM:
        zoom = float(custom_opts.get("zoom", 1.0))
        speed = float(custom_opts.get("speed", 1.0))
        pitch = float(custom_opts.get("pitch_semitones", custom_opts.get("pitch", 0.0)))
        grain = int(custom_opts.get("grain", 0))

        if randomize:
            if zoom > 1.0001:
                zoom = _jitter(zoom, 0.995, 1.015)
            if abs(speed - 1.0) > 0.0001:
                speed = _jitter(speed, 0.993, 1.007)
            if abs(pitch) > 0.0001:
                pitch += random.uniform(-0.03, 0.03)
            if trim_start > 0:
                trim_start = max(0.0, trim_start + random.uniform(-0.15, 0.15))

        if zoom > 1.0001:
            builder.add_subtle_crop_zoom(zoom)
        if grain > 0:
            builder.add_film_grain(grain)
        if custom_opts.get("color_grade", False):
            builder.add_color_grade()
        if custom_opts.get("subtitle_mask", False):
            builder.add_subtitle_mask()
        if custom_opts.get("hflip", False):
            builder.add_mirror_hflip()
        if custom_opts.get("pip", False):
            builder.add_smart_pip()
        if abs(speed - 1.0) > 0.0001:
            builder.set_sync_speed(speed)
        if abs(pitch) > 0.0001:
            builder.add_pitch_shift(pitch)
        if custom_opts.get("equalizer", False):
            builder.add_equalizer()
        if custom_opts.get("noise_floor", False):
            builder.add_noise_floor()

    # Apply trim across presets if configured
    if trim_start > 0.001 or trim_end > 0.001:
        builder.add_trim(trim_start, trim_end)

    return builder
