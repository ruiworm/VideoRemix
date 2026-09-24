"""Command Line Interface for VideoRemix."""

import argparse
import os
import sys
import time
from typing import Optional

# Ensure videoremix package root is on path when executed directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from videoremix import __version__
from videoremix.core.hardware import HardwareDetector
from videoremix.core.presets import PRESET_DESCRIPTIONS, PresetMode
from videoremix.queue.manager import BatchQueueManager
from videoremix.queue.task import RemediationTask, TaskStatus


def main():
    parser = argparse.ArgumentParser(
        prog="videoremix",
        description="VideoRemix: Next-generation multi-modal intelligent video deduplication engine.",
    )
    parser.add_argument("input", nargs="?", default=None, help="Path to input video file or directory")
    parser.add_argument("-o", "--output", help="Path to output file or output directory")
    parser.add_argument(
        "-p", "--preset",
        choices=["quality", "balanced", "pip", "custom"],
        default="balanced",
        help="Remediation preset mode (default: balanced)",
    )
    parser.add_argument("-w", "--workers", type=int, default=2, help="Number of concurrent transcode workers (default: 2)")
    parser.add_argument("-r", "--recursive", action="store_true", help="Recursively scan subdirectories if input is a directory")
    parser.add_argument("--force-cpu", action="store_true", help="Force software CPU libx264 encoding")
    parser.add_argument("--web", action="store_true", help="Launch local Web UI console in browser (recommended for WSL)")
    parser.add_argument("--gui", action="store_true", help="Launch desktop GUI window")

    # Custom options
    custom_grp = parser.add_argument_group("Custom Options (when --preset custom)")
    custom_grp.add_argument("--zoom", type=float, default=1.02, help="Subtle zoom ratio (e.g. 1.02)")
    custom_grp.add_argument("--speed", type=float, default=1.018, help="Synchronized A/V speed ratio (e.g. 1.018)")
    custom_grp.add_argument("--grain", type=int, default=3, help="Film grain noise intensity (1-10)")
    custom_grp.add_argument("--pitch", type=float, default=0.25, help="Pitch shift in semitones (e.g. 0.25)")
    custom_grp.add_argument("--hflip", action="store_true", help="Apply horizontal mirror flip")
    custom_grp.add_argument("--pip", action="store_true", help="Enable smart blurred picture-in-picture")

    parser.add_argument("-v", "--version", action="version", version=f"VideoRemix v{__version__}")

    args = parser.parse_args()

    if args.web:
        from videoremix.ui.web import main as web_main
        web_main()
        return

    if args.gui or args.input is None:
        if args.gui:
            from videoremix.ui.app import main as gui_main
            gui_main()
            return
        else:
            parser.print_help()
            print("\nTip: Run with --web to launch the local Web UI: videoremix --web")
            sys.exit(0)

    input_path = os.path.abspath(args.input)
    if not os.path.exists(input_path):
        print(f"Error: Input path '{input_path}' does not exist.", file=sys.stderr)
        sys.exit(1)

    preset_map = {
        "quality": PresetMode.QUALITY_FIRST,
        "balanced": PresetMode.BALANCED_REMIX,
        "pip": PresetMode.SMART_PIP,
        "custom": PresetMode.CUSTOM,
    }
    selected_preset = preset_map[args.preset]

    custom_opts = {}
    if selected_preset == PresetMode.CUSTOM:
        custom_opts = {
            "zoom": args.zoom,
            "speed": args.speed,
            "grain": args.grain,
            "pitch_semitones": args.pitch,
            "hflip": args.hflip,
            "pip": args.pip,
            "color_grade": True,
            "noise_floor": True,
        }

    # Print summary banner
    encoder = HardwareDetector.detect_best_encoder(force_cpu=args.force_cpu)
    print("=" * 60)
    print(f"VideoRemix Engine v{__version__}")
    print(f"Active Preset : {selected_preset.value} - {PRESET_DESCRIPTIONS[selected_preset]}")
    print(f"Selected Codec: {encoder.name}")
    print(f"Max Workers   : {args.workers}")
    print("=" * 60)

    manager = BatchQueueManager(max_workers=args.workers)

    if os.path.isdir(input_path):
        tasks = manager.add_directory(
            input_dir=input_path,
            output_dir=args.output,
            preset=selected_preset,
            recursive=args.recursive,
            **custom_opts,
        )
        print(f"Enqueued {len(tasks)} videos from directory: {input_path}")
    else:
        task = manager.add_task(
            input_path=input_path,
            output_path=args.output,
            preset=selected_preset,
            **custom_opts,
        )
        tasks = [task]
        print(f"Enqueued file: {task.filename} -> {task.output_path}")

    if not tasks:
        print("No compatible media files found to process.")
        sys.exit(0)

    # Progress tracking in terminal
    finished_count = 0
    total_count = len(tasks)

    def on_task_update(t: RemediationTask):
        nonlocal finished_count
        if t.status in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED):
            finished_count = sum(1 for x in tasks if x.status in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED))

    manager.on_task_update = on_task_update
    manager.start()

    print("\nProcessing queue in progress...")
    try:
        while finished_count < total_count:
            active_lines = []
            for t in tasks:
                if t.status == TaskStatus.RUNNING:
                    active_lines.append(f"[{t.filename[:18]:<18}] {t.progress:5.1f}% @ {t.speed} (ETA {t.eta:.0f}s)")
            status_summary = f"\r[Completed {finished_count}/{total_count}] " + " | ".join(active_lines[:2])
            sys.stdout.write(status_summary.ljust(80))
            sys.stdout.flush()
            time.sleep(0.3)
    except KeyboardInterrupt:
        print("\n\nOperation interrupted by user. Cancelling running tasks...")
        manager.stop_all()
        sys.exit(130)

    print(f"\n\nQueue execution complete! Processed {finished_count}/{total_count} files.")
    failures = [t for t in tasks if t.status == TaskStatus.FAILED]
    if failures:
        print(f"Warnings: {len(failures)} task(s) failed:")
        for f in failures:
            print(f" - {f.filename}: {f.error_message}")
        sys.exit(1)


if __name__ == "__main__":
    main()
