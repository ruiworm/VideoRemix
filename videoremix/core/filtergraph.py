"""Multi-modal filtergraph builder for video and audio remediation."""

import math
import random
import string
from typing import Dict, List, Optional
from videoremix.core.probe import MediaInfo


class FilterGraphBuilder:
    """Constructs robust, synchronized FFmpeg filter chains."""

    def __init__(self, media_info: MediaInfo):
        self.info = media_info
        self.video_filters: List[str] = []
        self.audio_filters: List[str] = []
        self.metadata_tags: Dict[str, str] = {}
        self.strip_metadata: bool = True
        self.speed_ratio: float = 1.0
        self.enable_smart_pip: bool = False
        self.pip_scale: float = 0.90
        self.pip_blur: int = 15

    # ------------------ Video Transformations ------------------

    def add_subtle_crop_zoom(self, zoom: float = 1.02) -> "FilterGraphBuilder":
        """Apply subtle digital zoom and center crop to alter spatial coordinate hash."""
        if abs(zoom - 1.0) < 0.001:
            return self
        # Scale slightly up and crop back to original resolution
        f = f"scale=iw*{zoom:.4f}:ih*{zoom:.4f}:flags=lanczos,crop=iw/{zoom:.4f}:ih/{zoom:.4f}:(iw-iw/{zoom:.4f})/2:(ih-ih/{zoom:.4f})/2"
        self.video_filters.append(f)
        return self

    def add_film_grain(self, intensity: int = 3) -> "FilterGraphBuilder":
        """Inject imperceptible high-frequency film grain to randomize spatial perceptual hashes."""
        if intensity <= 0:
            return self
        # Add slight temporal/spatial noise
        f = f"noise=c0s={intensity}:c0f=u:c1s={max(1, intensity-1)}:c1f=u"
        self.video_filters.append(f)
        return self

    def add_color_grade(
        self,
        contrast: float = 1.02,
        brightness: float = 0.008,
        saturation: float = 1.03,
        gamma: float = 1.01,
    ) -> "FilterGraphBuilder":
        """Subtle cinematic color grading without chromatic fringing."""
        f = f"eq=contrast={contrast:.3f}:brightness={brightness:.3f}:saturation={saturation:.3f}:gamma={gamma:.3f}"
        self.video_filters.append(f)
        return self

    def add_mirror_hflip(self) -> "FilterGraphBuilder":
        """Horizontal mirror flip."""
        self.video_filters.append("hflip")
        return self

    def add_smart_pip(self, scale: float = 0.90, blur: int = 15) -> "FilterGraphBuilder":
        """Wrap video in a blurred dynamic background (Picture-in-Picture)."""
        self.enable_smart_pip = True
        self.pip_scale = scale
        self.pip_blur = blur
        return self

    def add_subtitle_mask(self, height_ratio: float = 0.12, opacity: float = 0.70) -> "FilterGraphBuilder":
        """Apply a semi-transparent bottom banner to disrupt OCR subtitle recognition."""
        if not self.info.has_video or height_ratio <= 0.0:
            return self
        f = f"drawbox=x=0:y=ih*(1.0-{height_ratio:.3f}):w=iw:h=ih*{height_ratio:.3f}:color=black@{opacity:.2f}:t=fill"
        self.video_filters.append(f)
        return self

    # ------------------ Audio Transformations ------------------

    def add_pitch_shift(self, semitones: float = 0.25) -> "FilterGraphBuilder":
        """Shift pitch subtly by semitones while keeping original audio duration intact."""
        if not self.info.has_audio or abs(semitones) < 0.01:
            return self
        factor = 2.0 ** (semitones / 12.0)
        sr = self.info.sample_rate or 44100
        # asetrate shifts pitch and speed; atempo restores original speed
        f = f"asetrate={sr}*{factor:.4f},atempo={1.0 / factor:.4f},aresample={sr}"
        self.audio_filters.append(f)
        return self

    def add_equalizer(self, low_gain_db: float = 0.8, high_gain_db: float = -0.8) -> "FilterGraphBuilder":
        """Subtly alter acoustic frequency curve to break spectral fingerprinting."""
        if not self.info.has_audio:
            return self
        f = f"equalizer=f=120:width_type=o:w=1:g={low_gain_db:.2f},equalizer=f=8000:width_type=o:w=1:g={high_gain_db:.2f}"
        self.audio_filters.append(f)
        return self

    def add_noise_floor(self) -> "FilterGraphBuilder":
        """Add microscopic dither noise floor below human hearing threshold."""
        if not self.info.has_audio:
            return self
        # Sub-perceptual dither perturbation (~-50dB)
        f = "aformat=sample_fmts=fltp,aeval=val(0)+0.00008*random(0):c=same"
        self.audio_filters.append(f)
        return self

    # ------------------ Synchronization & Speed ------------------

    def set_sync_speed(self, speed_ratio: float = 1.015) -> "FilterGraphBuilder":
        """Synchronously adjust video and audio speed to maintain sample-accurate lip-sync."""
        if abs(speed_ratio - 1.0) < 0.001:
            return self
        self.speed_ratio = speed_ratio
        return self

    # ------------------ Metadata & Hash ------------------

    def set_clean_metadata(self, randomize_tags: bool = True) -> "FilterGraphBuilder":
        """Clear existing encoder/camera metadata and inject fresh pseudo tags."""
        self.strip_metadata = True
        if randomize_tags:
            rand_id = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
            self.metadata_tags["title"] = f"VID_{rand_id}"
            self.metadata_tags["comment"] = "VideoRemix Engine"
        return self

    # ------------------ Build Command Args ------------------

    def build_ffmpeg_args(self) -> List[str]:
        """Assemble all configured video/audio filters and metadata into FFmpeg CLI arguments."""
        args: List[str] = []

        # Strip metadata
        if self.strip_metadata:
            args.extend(["-map_metadata", "-1"])

        for key, val in self.metadata_tags.items():
            args.extend(["-metadata", f"{key}={val}"])

        # Prepare speed adjustments
        v_filters = list(self.video_filters)
        a_filters = list(self.audio_filters)

        if abs(self.speed_ratio - 1.0) >= 0.001:
            v_filters.append(f"setpts=PTS/{self.speed_ratio:.4f}")
            if self.info.has_audio:
                a_filters.append(f"atempo={self.speed_ratio:.4f}")

        # Assemble filter chains
        if self.enable_smart_pip and self.info.has_video:
            # Complex filter for Picture-in-Picture
            scale = self.pip_scale
            blur = self.pip_blur
            pip_v = (
                f"[0:v]split=2[bg_raw][fg_raw]; "
                f"[bg_raw]scale=iw:ih,boxblur={blur}:5[bg]; "
                f"[fg_raw]scale=iw*{scale:.3f}:ih*{scale:.3f}[fg]; "
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
            )
            if v_filters:
                pip_v += "," + ",".join(v_filters)
            pip_v += "[vout]"

            if a_filters and self.info.has_audio:
                filter_complex = f"{pip_v}; [0:a]{','.join(a_filters)}[aout]"
                args.extend(["-filter_complex", filter_complex, "-map", "[vout]", "-map", "[aout]"])
            else:
                args.extend(["-filter_complex", pip_v, "-map", "[vout]"])
                if self.info.has_audio:
                    args.extend(["-map", "0:a?"])
        else:
            # Standard video filter chain
            if v_filters and self.info.has_video:
                args.extend(["-vf", ",".join(v_filters)])

            # Audio filter chain
            if a_filters and self.info.has_audio:
                args.extend(["-af", ",".join(a_filters)])

        return args
