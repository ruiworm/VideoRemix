"""Comprehensive unit tests verifying all fixes, Windows compatibility, and error handling."""

import os
import sys
from unittest.mock import MagicMock, patch
import pytest

from videoremix.core.executor import FFmpegExecutor
from videoremix.core.hardware import EncoderConfig, HardwareDetector
from videoremix.core.presets import PresetMode
from videoremix.core.probe import get_ffmpeg_bin, probe_media
from videoremix.launcher import setup_windows_dpi_awareness as launcher_dpi_setup
from videoremix.queue.manager import BatchQueueManager
from videoremix.queue.task import RemediationTask, TaskStatus
from videoremix.ui.app import setup_windows_dpi_awareness as app_dpi_setup


def test_windows_dpi_awareness_fallback_chain():
    """Verify that when earlier DPI APIs fail, the fallback chain actually executes."""
    mock_ctypes = MagicMock()

    # Case 1: SetProcessDpiAwarenessContext returns 0 (FALSE) -> should fall back to SetProcessDpiAwareness
    # SetProcessDpiAwareness returns non-zero (-1, E_FAIL) -> should fall back to SetProcessDPIAware
    mock_ctypes.windll.user32.SetProcessDpiAwarenessContext.return_value = 0
    mock_ctypes.windll.shcore.SetProcessDpiAwareness.return_value = -1
    mock_ctypes.windll.user32.SetProcessDPIAware.return_value = 1

    with patch.dict(sys.modules, {"ctypes": mock_ctypes}):
        with patch("sys.platform", "win32"), patch("os.name", "nt"):
            launcher_dpi_setup()
            assert mock_ctypes.windll.user32.SetProcessDpiAwarenessContext.called
            assert mock_ctypes.windll.shcore.SetProcessDpiAwareness.called
            assert mock_ctypes.windll.user32.SetProcessDPIAware.called

    mock_ctypes.reset_mock()
    # Case 2: SetProcessDpiAwarenessContext succeeds (returns 1) -> should NOT call fallbacks
    mock_ctypes.windll.user32.SetProcessDpiAwarenessContext.return_value = 1
    with patch.dict(sys.modules, {"ctypes": mock_ctypes}):
        with patch("sys.platform", "win32"), patch("os.name", "nt"):
            app_dpi_setup()
            assert mock_ctypes.windll.user32.SetProcessDpiAwarenessContext.called
            assert not mock_ctypes.windll.shcore.SetProcessDpiAwareness.called
            assert not mock_ctypes.windll.user32.SetProcessDPIAware.called


def test_probe_corrupt_file_raises_descriptive_error(tmp_path):
    """Probing an empty/corrupt file should raise RuntimeError with FFmpeg stderr tail."""
    corrupt_file = tmp_path / "corrupt.mp4"
    corrupt_file.write_text("not a real video file at all\ncorrupt header content\n")

    with pytest.raises(RuntimeError) as exc_info:
        probe_media(str(corrupt_file))

    err_text = str(exc_info.value)
    assert "No video or audio streams detected" in err_text or "No video or audio stream found" in err_text
    assert "FFmpeg stderr tail:" in err_text or "corrupt" in err_text.lower()


def test_get_ffmpeg_bin_ignores_non_executables_in_meipass(tmp_path):
    """get_ffmpeg_bin must not pick up non-binary files like ffmpeg.py or ffmpeg.txt from _MEIPASS."""
    meipass_dir = tmp_path / "fake_meipass"
    meipass_dir.mkdir()

    # Create dummy non-executable files
    (meipass_dir / "ffmpeg.py").write_text("print('fake ffmpeg')")
    (meipass_dir / "ffmpeg_notes.txt").write_text("notes")

    # Also create a valid mock binary
    bin_dir = meipass_dir / "bin"
    bin_dir.mkdir()
    valid_ffmpeg = bin_dir / ("ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg")
    valid_ffmpeg.write_bytes(b"\x7fELF" if not sys.platform.startswith("win") else b"MZ")
    if not sys.platform.startswith("win"):
        os.chmod(valid_ffmpeg, 0o755)

    with patch("sys.frozen", True, create=True), patch("sys._MEIPASS", str(meipass_dir), create=True):
        found = get_ffmpeg_bin()
        assert not found.endswith(".py")
        assert not found.endswith(".txt")
        assert os.path.abspath(str(valid_ffmpeg)) == os.path.abspath(found)


def test_executor_command_args_and_pix_fmt(sample_video, tmp_path):
    """FFmpegExecutor must include -nostdin and ensure -pix_fmt yuv420p is injected."""
    from videoremix.core.filtergraph import FilterGraphBuilder

    info = probe_media(sample_video)
    builder = FilterGraphBuilder(info)
    builder.add_subtle_crop_zoom(1.02)

    hw_cfg = EncoderConfig(
        video_codec="libx264",
        audio_codec="aac",
        video_args=["-preset", "ultrafast"],
        is_hardware=False,
    )

    out_file = str(tmp_path / "out_pixfmt.mp4")
    executor = FFmpegExecutor()

    captured_cmds = []
    orig_popen = None

    import subprocess
    real_popen = subprocess.Popen

    def mock_popen(cmd, *args, **kwargs):
        captured_cmds.append(cmd)
        # Check stdin is DEVNULL
        assert kwargs.get("stdin") == subprocess.DEVNULL
        assert kwargs.get("encoding") == "utf-8"
        assert kwargs.get("errors") == "replace"
        return real_popen(cmd, *args, **kwargs)

    with patch("subprocess.Popen", side_effect=mock_popen):
        res = executor.run_remediation(info, builder, out_file, encoder_config=hw_cfg)
        assert os.path.exists(res)

    assert len(captured_cmds) == 1
    cmd = captured_cmds[0]
    assert "-nostdin" in cmd
    assert "-pix_fmt" in cmd
    pix_idx = cmd.index("-pix_fmt")
    assert cmd[pix_idx + 1] == "yuv420p"


def test_executor_error_tail_on_failure(sample_video, tmp_path):
    """When FFmpeg fails with non-zero code, last stderr lines should be in RuntimeError."""
    from videoremix.core.filtergraph import FilterGraphBuilder

    info = probe_media(sample_video)
    builder = FilterGraphBuilder(info)

    # Supply an invalid video codec to force FFmpeg failure
    bad_cfg = EncoderConfig(
        video_codec="nonexistent_bogus_codec",
        audio_codec="aac",
        video_args=[],
    )

    out_file = str(tmp_path / "bad_codec.mp4")
    executor = FFmpegExecutor()

    with pytest.raises(RuntimeError) as exc_info:
        executor.run_remediation(info, builder, out_file, encoder_config=bad_cfg)

    err_str = str(exc_info.value)
    assert "FFmpeg process exited with code" in err_str
    assert "FFmpeg stderr:" in err_str


def test_queue_hardware_fallback_to_cpu(sample_video, tmp_path):
    """When hardware encoder fails, queue manager should catch it and retry with CPU encoder."""
    qm = BatchQueueManager(max_workers=1)
    out_file = str(tmp_path / "hw_fallback.mp4")
    task = qm.add_task(sample_video, out_file, PresetMode.QUALITY_FIRST)

    mock_hw_encoder = EncoderConfig(
        video_codec="h264_nvenc_simulated",
        audio_codec="aac",
        video_args=[],
        is_hardware=True,
        name="Mock NVENC",
    )

    calls = []
    orig_run = FFmpegExecutor.run_remediation

    def patched_run(self, media_info, builder, output_path, encoder_config=None, on_progress=None):
        calls.append(encoder_config)
        if getattr(encoder_config, "is_hardware", False):
            raise RuntimeError("Simulated NVENC hardware initialization failure")
        return orig_run(self, media_info, builder, output_path, encoder_config, on_progress)

    with patch.object(FFmpegExecutor, "run_remediation", patched_run):
        # Force worker loop to use mock_hw_encoder
        with patch.object(HardwareDetector, "detect_best_encoder", return_value=mock_hw_encoder):
            # But force_cpu returns CPU config
            def mock_detect(force_cpu=False):
                if force_cpu:
                    return EncoderConfig(video_codec="libx264", audio_codec="aac", is_hardware=False, name="CPU fallback")
                return mock_hw_encoder
            with patch.object(HardwareDetector, "detect_best_encoder", side_effect=mock_detect):
                qm.start()
                import time
                for _ in range(30):
                    if task.status in (TaskStatus.SUCCESS, TaskStatus.FAILED):
                        break
                    time.sleep(0.2)

    assert task.status == TaskStatus.SUCCESS
    assert len(calls) == 2
    assert calls[0].is_hardware is True
    assert calls[1].is_hardware is False
    assert os.path.exists(out_file)


def test_queue_overwrite_protection(tmp_path):
    """Queue manager add_task and UI _add_files must protect against input file overwrite."""
    input_file = tmp_path / "original.mp4"
    input_file.write_text("fake video content")

    qm = BatchQueueManager()
    # If same input path and output path passed, should append _remix
    task = qm.add_task(str(input_file), str(input_file))
    assert task.output_path != str(input_file)
    assert task.output_path.endswith("original_remix.mp4")


def test_ui_add_files_and_double_click_error_dialog(tmp_path):
    """Test VideoRemixApp file adding and double-click error modal behavior."""
    import tkinter as tk
    from unittest.mock import MagicMock, patch
    from videoremix.ui.app import VideoRemixApp

    root = tk.Tk()
    root.withdraw()
    try:
        app = VideoRemixApp(root)

        # 1. Test adding files with custom output directory
        out_dir = tmp_path / "custom_output"
        out_dir.mkdir()
        app.output_dir_var.set(str(out_dir))

        in_file = tmp_path / "video1.mp4"
        in_file.write_text("dummy")

        with patch("tkinter.filedialog.askopenfilenames", return_value=[str(in_file)]):
            app._add_files()

        assert len(app.queue_manager.tasks) == 1
        added_task = app.queue_manager.tasks[0]
        assert added_task.output_path == str(out_dir / "video1.mp4")

        # 2. Test adding file where output_dir == input file directory (same name protection)
        in_file2 = out_dir / "video2.mp4"
        in_file2.write_text("dummy")
        with patch("tkinter.filedialog.askopenfilenames", return_value=[str(in_file2)]):
            app._add_files()

        assert len(app.queue_manager.tasks) == 2
        added_task2 = app.queue_manager.tasks[1]
        assert added_task2.output_path == str(out_dir / "video2_remix.mp4")

        # 3. Test double-click on failed task triggers messagebox.showerror
        added_task2.status = TaskStatus.FAILED
        added_task2.error_message = "Simulated fatal transcode error"
        app._sync_task_ui(added_task2)

        tree_iid = app._task_tree_items[added_task2.task_id]
        mock_event = MagicMock()
        mock_event.y = 10

        with patch.object(app.tree, "identify_row", return_value=tree_iid):
            with patch("tkinter.messagebox.showerror") as mock_err_box:
                app._on_tree_double_click(mock_event)
                assert mock_err_box.called
                args, _ = mock_err_box.call_args
                assert "Simulated fatal transcode error" in args[1]

        # 4. Double click on non-failed task does not show error dialog
        added_task.status = TaskStatus.SUCCESS
        app._sync_task_ui(added_task)
        tree_iid1 = app._task_tree_items[added_task.task_id]
        with patch.object(app.tree, "identify_row", return_value=tree_iid1):
            with patch("tkinter.messagebox.showerror") as mock_err_box:
                app._on_tree_double_click(mock_event)
                assert not mock_err_box.called

        # 5. Double click outside rows (identify_row returns "") does not show error dialog
        with patch.object(app.tree, "identify_row", return_value=""):
            with patch("tkinter.messagebox.showerror") as mock_err_box:
                app._on_tree_double_click(mock_event)
                assert not mock_err_box.called

    finally:
        root.destroy()


def test_hardware_detector_subprocesses_use_safe_kwargs():
    """Verify HardwareDetector passes safe kwargs (DEVNULL, encoding, CREATE_NO_WINDOW) to subprocess."""
    import subprocess
    captured_kwargs = []

    orig_run = subprocess.run

    def mock_run(*args, **kwargs):
        captured_kwargs.append(kwargs)
        # Return dummy encoders output
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = " V..... libx264\n"
        return mock_res

    with patch("sys.platform", "win32"), patch("os.name", "nt"):
        with patch("subprocess.run", side_effect=mock_run):
            HardwareDetector.get_supported_encoders(ffmpeg_bin="ffmpeg.exe")
            HardwareDetector._test_encoder("libx264", ffmpeg_bin="ffmpeg.exe")

    assert len(captured_kwargs) == 2
    for kw in captured_kwargs:
        assert kw.get("stdin") == subprocess.DEVNULL
        assert kw.get("creationflags") == getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

